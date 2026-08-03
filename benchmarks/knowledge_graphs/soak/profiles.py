"""Named soak profiles (KGP-031).

Short profiles are mandatory for CI. The 24-hour mixed soak is opt-in and
only runs after short profiles pass (enforced by the runner and tests).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Dict, Mapping, Optional, Tuple

JSONDict = Dict[str, Any]


@dataclass(frozen=True, slots=True)
class SoakProfile:
    """Duration and mix configuration for a longevity run."""

    name: str
    description: str
    duration_s: float
    sample_interval_s: float
    graph_count: int
    ops_per_tick: int
    write_weight: float
    read_weight: float
    compact_every_ticks: int
    inject_fault_every_ticks: int
    tick_interval_s: float
    opt_in: bool
    seed: int
    tags: Tuple[str, ...] = ()

    def to_json_dict(self) -> JSONDict:
        return {
            "name": self.name,
            "description": self.description,
            "duration_s": self.duration_s,
            "sample_interval_s": self.sample_interval_s,
            "graph_count": self.graph_count,
            "ops_per_tick": self.ops_per_tick,
            "write_weight": self.write_weight,
            "read_weight": self.read_weight,
            "compact_every_ticks": self.compact_every_ticks,
            "inject_fault_every_ticks": self.inject_fault_every_ticks,
            "tick_interval_s": self.tick_interval_s,
            "opt_in": self.opt_in,
            "seed": self.seed,
            "tags": list(self.tags),
        }

    def with_duration(self, duration_s: float) -> "SoakProfile":
        return replace(self, duration_s=float(duration_s))


# CI-mandatory short mixed soak (~a few seconds of wall time).
SHORT = SoakProfile(
    name="short",
    description="CI short mixed soak: multi-graph write/read + compaction + sampling.",
    duration_s=2.0,
    sample_interval_s=0.25,
    graph_count=4,
    ops_per_tick=4,
    write_weight=0.55,
    read_weight=0.45,
    compact_every_ticks=2,
    inject_fault_every_ticks=0,  # no destructive faults in short CI soak
    tick_interval_s=0.0,
    opt_in=False,
    seed=31,
    tags=("ci", "soak", "mandatory", "short"),
)

# Intermediate profile for pre-24h gates.
MEDIUM = SoakProfile(
    name="medium",
    description="Medium soak (~60s) for pre-release longevity.",
    duration_s=60.0,
    sample_interval_s=1.0,
    graph_count=8,
    ops_per_tick=8,
    write_weight=0.5,
    read_weight=0.5,
    compact_every_ticks=5,
    inject_fault_every_ticks=0,
    tick_interval_s=0.125,  # cap at roughly 64 operations/second
    opt_in=True,
    seed=310,
    tags=("soak", "medium", "opt-in"),
)

# Plan: 24-hour mixed soak after shorter suite is stable.
DAY = SoakProfile(
    name="day",
    description="24-hour mixed soak (opt-in; run only after short/medium pass).",
    duration_s=24 * 3600.0,
    sample_interval_s=60.0,
    graph_count=16,
    ops_per_tick=16,
    write_weight=0.45,
    read_weight=0.55,
    compact_every_ticks=20,
    inject_fault_every_ticks=0,
    tick_interval_s=1.0,  # cap at 16 operations/second
    opt_in=True,
    seed=24,
    tags=("soak", "24h", "opt-in"),
)

SOAK_PROFILES: Dict[str, SoakProfile] = {
    SHORT.name: SHORT,
    MEDIUM.name: MEDIUM,
    DAY.name: DAY,
}

PROFILE_NAMES: Tuple[str, ...] = tuple(SOAK_PROFILES.keys())


def get_soak_profile(name: str) -> SoakProfile:
    key = name.strip().lower().replace("-", "_")
    # Aliases
    aliases = {
        "24h": "day",
        "24_hour": "day",
        "twenty_four_hour": "day",
        "ci": "short",
        "tiny": "short",
    }
    key = aliases.get(key, key)
    try:
        return SOAK_PROFILES[key]
    except KeyError as exc:
        raise KeyError(
            f"unknown soak profile {name!r}; known: {sorted(SOAK_PROFILES)}"
        ) from exc


def resolve_duration_override(profile: SoakProfile) -> SoakProfile:
    """
    Apply environment overrides.

    * ``KG_SOAK_DURATION_S`` — absolute duration seconds
    * ``KG_SOAK_24H=1`` — force the day profile duration (still opt-in)
    """
    if os.environ.get("KG_SOAK_24H", "").strip() in {"1", "true", "yes"}:
        profile = DAY
    raw = os.environ.get("KG_SOAK_DURATION_S", "").strip()
    if raw:
        return profile.with_duration(float(raw))
    return profile


def short_profiles_required() -> Tuple[SoakProfile, ...]:
    return tuple(p for p in SOAK_PROFILES.values() if not p.opt_in)
