"""KGP-031: soak / longevity load tests.

Mandatory:
* short mixed soak completes with no data/security errors
* growth analyzer rejects unbounded RSS and accepts stable series
* 24h profile is opt-in and gated behind short profile success

The full 24-hour run is skipped unless ``KG_SOAK_24H=1`` (or an explicit
duration override) is set in the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from benchmarks.knowledge_graphs.soak import (
    DAY,
    SHORT,
    SOAK_RECEIPT_SCHEMA,
    analyze_growth,
    get_soak_profile,
    resolve_duration_override,
    run_soak,
    short_profiles_required,
    synthesize_stable_samples,
    synthesize_unbounded_samples,
    write_soak_receipt,
)


class TestSoakProfiles:
    def test_short_is_mandatory(self) -> None:
        p = get_soak_profile("short")
        assert p.opt_in is False
        assert p.duration_s > 0
        assert p.graph_count >= 1
        assert short_profiles_required()[0].name == "short"

    def test_day_is_24h_opt_in(self) -> None:
        p = get_soak_profile("24h")
        assert p.name == "day"
        assert p.opt_in is True
        assert p.duration_s == pytest.approx(24 * 3600.0)
        assert p.graph_count >= 16

    def test_aliases(self) -> None:
        assert get_soak_profile("ci").name == "short"
        assert get_soak_profile("day").name == "day"

    def test_24h_opt_in_does_not_promote_short_profile(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KG_SOAK_24H", "1")
        assert resolve_duration_override(SHORT).name == "short"
        assert resolve_duration_override(SHORT).duration_s == SHORT.duration_s


class TestGrowthAnalyzer:
    def test_stable_series_passes(self) -> None:
        samples = synthesize_stable_samples(n=30)
        report = analyze_growth(samples)
        assert report.ok
        assert not report.unbounded
        assert report.data_errors == 0
        assert report.security_errors == 0

    def test_unbounded_rss_fails(self) -> None:
        samples = synthesize_unbounded_samples(n=30, rss_per_step=1_000_000.0)
        report = analyze_growth(samples)
        assert report.unbounded
        assert not report.ok
        rss = next(s for s in report.series if s.name == "rss_bytes")
        assert rss.unbounded
        assert rss.slope_per_s > 0

    def test_data_errors_fail_gate(self) -> None:
        samples = synthesize_stable_samples(n=10)
        report = analyze_growth(samples, data_errors=1)
        assert not report.ok
        assert report.data_errors == 1

    def test_security_errors_fail_gate(self) -> None:
        samples = synthesize_stable_samples(n=10)
        report = analyze_growth(samples, security_errors=2)
        assert not report.ok
        assert report.security_errors == 2


class TestShortSoakRun:
    def test_short_soak_passes_growth_and_receipt(self, tmp_path: Path) -> None:
        result = run_soak(
            SHORT,
            work_dir=tmp_path,
            require_short_first=False,
        )
        assert result.status == "success", result.growth.summary
        assert result.growth.ok
        assert result.growth.data_errors == 0
        assert result.growth.security_errors == 0
        assert result.operations > 0
        assert result.ticks > 0
        assert len(result.samples) >= 2
        receipt = result.receipt
        assert receipt["schema"] == SOAK_RECEIPT_SCHEMA
        assert receipt["status"] == "success"
        assert receipt["digest"]
        assert "rss_bytes" in result.samples[0]
        assert "open_fds" in result.samples[0]
        assert "wal_entries" in result.samples[0]
        assert "lease_count" in result.samples[0]
        assert "cache_bytes" in result.samples[0]

        path = write_soak_receipt(receipt, tmp_path / "soak-receipt.json")
        assert path.is_file()
        assert path.stat().st_size > 0

    def test_short_soak_records_latency_and_recovery(self, tmp_path: Path) -> None:
        result = run_soak(SHORT, work_dir=tmp_path, require_short_first=False)
        assert result.latency.count >= result.operations
        counters = result.counters.to_json_dict()
        assert counters["recovery_attempts"] >= 1
        assert counters["recovery_successes"] >= 1


class TestDaySoakGate:
    def test_day_requires_short_first(self, tmp_path: Path) -> None:
        """Opt-in profile auto-runs short gate first (duration kept tiny for CI)."""
        old = os.environ.get("KG_SOAK_DURATION_S")
        # Clear env override so profile.with_duration is authoritative.
        os.environ.pop("KG_SOAK_DURATION_S", None)
        try:
            medium = get_soak_profile("medium").with_duration(1.5)
            result = run_soak(
                medium,
                work_dir=tmp_path,
                require_short_first=True,
                short_already_passed=False,
            )
            assert result.status == "success", result.growth.summary
            assert result.growth.ok
        finally:
            if old is None:
                os.environ.pop("KG_SOAK_DURATION_S", None)
            else:
                os.environ["KG_SOAK_DURATION_S"] = old

    @pytest.mark.skipif(
        os.environ.get("KG_SOAK_24H", "").strip() not in {"1", "true", "yes"},
        reason="24h soak is opt-in; set KG_SOAK_24H=1 to enable",
    )
    def test_full_24h_mixed_soak(self, tmp_path: Path) -> None:
        """Full plan soak: only executed when explicitly enabled."""
        result = run_soak(
            DAY,
            work_dir=tmp_path,
            require_short_first=True,
            short_already_passed=False,
        )
        receipt_path = os.environ.get("KG_SOAK_RECEIPT_PATH", "").strip()
        if receipt_path:
            write_soak_receipt(result.receipt, Path(receipt_path))
        assert result.status == "success", result.growth.summary
        assert result.growth.ok
        assert result.growth.data_errors == 0
        assert result.growth.security_errors == 0
        assert result.elapsed_s >= DAY.duration_s * 0.95
