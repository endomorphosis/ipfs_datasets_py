"""Fail-closed tests for long-profile resource and opt-in guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.knowledge_graphs.harness import run_profile
from benchmarks.knowledge_graphs.safety import (
    GIB,
    BenchmarkSafetyError,
    ResourceGuard,
    ResourceLimits,
    ResourceSnapshot,
    synthetic_large_guard,
)
from benchmarks.knowledge_graphs.soak import DAY, run_soak


def test_synthetic_large_requires_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkSafetyError, match="KG_LOAD_SYNTHETIC_LARGE=1"):
        run_profile("synthetic_large", work_dir=tmp_path)
    assert not (tmp_path / "receipts").exists()


def test_synthetic_large_preflight_fails_before_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KG_LOAD_SYNTHETIC_LARGE", "1")
    monkeypatch.setattr(
        "benchmarks.knowledge_graphs.safety.snapshot_resources",
        lambda path: ResourceSnapshot(
            available_memory_bytes=4 * GIB,
            process_rss_bytes=100,
            free_disk_bytes=1_000 * GIB,
        ),
    )
    with pytest.raises(BenchmarkSafetyError, match="resource preflight failed"):
        synthetic_large_guard(tmp_path)


def test_runtime_guard_aborts_at_rss_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "benchmarks.knowledge_graphs.safety.snapshot_resources",
        lambda path: ResourceSnapshot(
            available_memory_bytes=20 * GIB,
            process_rss_bytes=3 * GIB,
            free_disk_bytes=20 * GIB,
        ),
    )
    guard = ResourceGuard(
        tmp_path,
        ResourceLimits(
            min_available_start_bytes=10 * GIB,
            min_available_runtime_bytes=2 * GIB,
            min_free_disk_bytes=10 * GIB,
            max_process_rss_bytes=2 * GIB,
        ),
        label="test",
    )
    with pytest.raises(BenchmarkSafetyError, match="RSS"):
        guard.check()


def test_day_soak_requires_explicit_opt_in(tmp_path: Path) -> None:
    with pytest.raises(BenchmarkSafetyError, match="KG_SOAK_24H=1"):
        run_soak(
            DAY,
            work_dir=tmp_path,
            require_short_first=False,
            short_already_passed=True,
        )


def test_long_soak_profiles_are_rate_limited() -> None:
    assert DAY.tick_interval_s > 0
    assert DAY.ops_per_tick / DAY.tick_interval_s <= 16
