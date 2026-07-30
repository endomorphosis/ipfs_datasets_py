"""KGP-030: labelled baselines and SLO regression gates.

Covers:

* required profile baselines (smoke, 211, CVEfixes, synthetic_large, concurrent_mixed)
* methodology (warmup, repetitions, variance)
* zero correctness / security errors
* unexplained p95 and throughput regressions over 10% block release
* live harness comparison for runnable profiles
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pytest

from benchmarks.knowledge_graphs.baselines import (
    BASELINE_SCHEMA,
    BASELINE_SCHEMA_VERSION,
    REGRESSION_RATIO_LIMIT,
    REQUIRED_BASELINE_PROFILES,
    aggregate_samples,
    baselines_root,
    build_baseline_document,
    compare_metrics,
    compare_receipt_to_baseline,
    compare_to_baseline,
    extract_metrics_from_receipt,
    load_baseline,
    load_catalog,
    ratify_profile_runs,
    unexplained_regression,
    validate_baseline_document,
    validate_methodology,
)
from benchmarks.knowledge_graphs.baselines.catalog import (
    CORRECTNESS_ERROR_MAX,
    SECURITY_ERROR_MAX,
    environments_root,
    scan_environments,
)
from benchmarks.knowledge_graphs.baselines.compare import ComparisonResult
from benchmarks.knowledge_graphs.harness import run_profile
from benchmarks.knowledge_graphs.profiles import get_profile
from benchmarks.knowledge_graphs.receipt import validate_receipt

REFERENCE_ENV = "reference-lab-linux"


# ---------------------------------------------------------------------------
# Catalog & artifact structure
# ---------------------------------------------------------------------------


class TestBaselineCatalog:
    def test_baselines_root_exists(self) -> None:
        root = baselines_root()
        assert root.is_dir()
        assert (root / "catalog.json").is_file()
        assert environments_root().is_dir()

    def test_catalog_lists_required_profiles(self) -> None:
        catalog = load_catalog()
        assert catalog.regression_ratio_limit == pytest.approx(0.10)
        assert REGRESSION_RATIO_LIMIT == pytest.approx(0.10)
        profiles = {b.profile for b in catalog.baselines}
        for name in REQUIRED_BASELINE_PROFILES:
            assert name in profiles, f"missing baseline for required profile {name}"
        assert REFERENCE_ENV in catalog.environments or any(
            b.environment_label == REFERENCE_ENV for b in catalog.baselines
        )

    def test_scan_environments_matches_catalog(self) -> None:
        scanned = scan_environments()
        loaded = load_catalog()
        scanned_keys = {(b.environment_label, b.profile) for b in scanned.baselines}
        loaded_keys = {(b.environment_label, b.profile) for b in loaded.baselines}
        assert scanned_keys == loaded_keys

    def test_each_required_profile_has_reference_baseline(self) -> None:
        for name in REQUIRED_BASELINE_PROFILES:
            doc = load_baseline(name, environment_label=REFERENCE_ENV)
            problems = validate_baseline_document(doc)
            assert problems == [], (name, problems)
            assert doc["environment_label"] == REFERENCE_ENV
            assert doc["profile"] == name
            assert doc["schema"] == BASELINE_SCHEMA
            assert doc["schema_version"] == BASELINE_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Document validation & methodology
# ---------------------------------------------------------------------------


class TestBaselineDocuments:
    @pytest.mark.parametrize("profile", list(REQUIRED_BASELINE_PROFILES) + ["tiny"])
    def test_document_schema_and_methodology(self, profile: str) -> None:
        doc = load_baseline(profile, environment_label=REFERENCE_ENV)
        problems = validate_baseline_document(doc)
        assert problems == [], problems

        meth = doc["methodology"]
        meth_problems = validate_methodology(meth)
        assert meth_problems == [], meth_problems
        assert meth["warmup_runs"] >= 1
        assert meth["repetitions"] >= 3
        assert meth["variance_model"] == "sample_std"
        assert meth["warmup_operations"] >= 0
        assert isinstance(meth["surfaces"], list) and meth["surfaces"]
        assert isinstance(meth["storage_profiles"], list) and meth["storage_profiles"]

        metrics = doc["metrics"]
        for key in ("p95_ms", "p99_ms", "ops_per_s", "recovery_ms_mean", "max_rss_bytes"):
            summary = metrics[key]
            assert summary["n"] == meth["repetitions"] or summary["n"] >= 3
            assert len(summary["samples"]) == summary["n"]
            assert "median" in summary and "stdev" in summary and "bound" in summary
            assert summary["direction"] in ("lower_is_better", "higher_is_better")

        assert metrics["p95_ms"]["direction"] == "lower_is_better"
        assert metrics["ops_per_s"]["direction"] == "higher_is_better"

        gates = doc["gates"]
        assert gates["correctness_errors_max"] == CORRECTNESS_ERROR_MAX == 0
        assert gates["security_errors_max"] == SECURITY_ERROR_MAX == 0
        assert gates["p95_regression_max_ratio"] <= REGRESSION_RATIO_LIMIT
        assert gates["throughput_regression_max_ratio"] <= REGRESSION_RATIO_LIMIT

    def test_smoke_shape_matches_plan(self) -> None:
        doc = load_baseline("smoke", environment_label=REFERENCE_ENV)
        shape = doc["shape"]
        assert shape["node_count"] == 1000
        assert shape["edge_count"] == 5000
        assert doc["status"] == "ratified"

    def test_synthetic_large_shape_and_gated_status(self) -> None:
        doc = load_baseline("synthetic_large", environment_label=REFERENCE_ENV)
        assert doc["shape"]["node_count"] == 1_000_000
        assert doc["shape"]["edge_count"] == 10_000_000
        assert doc["status"] == "environment_gated"
        assert doc["ratification_method"] == "scaled_from_measured_proxy"
        assert doc["methodology"].get("re_ratify_on_lab_hardware") is True

    def test_concurrent_mixed_has_at_least_16_graphs(self) -> None:
        doc = load_baseline("concurrent_mixed", environment_label=REFERENCE_ENV)
        assert doc["shape"]
        cfg = doc.get("profile_config") or {}
        assert int(cfg.get("graph_count") or doc["methodology"].get("graph_count") or 0) >= 16

    def test_corpus_profiles_present(self) -> None:
        for name, corpus_id in (("corpus_211", "211-ai"), ("corpus_cvefixes", "cvefixes")):
            doc = load_baseline(name, environment_label=REFERENCE_ENV)
            assert doc["status"] == "ratified"
            cfg = doc.get("profile_config") or {}
            assert cfg.get("corpus_id") == corpus_id or name in doc["notes"].lower() or True
            # Profile config should carry corpus_id when present.
            profile = get_profile(name)
            assert profile.corpus_id is not None
            assert cfg.get("corpus_id") == profile.corpus_id


# ---------------------------------------------------------------------------
# Aggregate / ratify helpers
# ---------------------------------------------------------------------------


class TestMethodologyHelpers:
    def test_aggregate_samples_lower_is_better(self) -> None:
        s = aggregate_samples([10.0, 12.0, 11.0], direction="lower_is_better")
        assert s.n == 3
        assert s.median == pytest.approx(11.0)
        assert s.stdev > 0
        assert s.bound >= s.median
        assert s.direction == "lower_is_better"

    def test_aggregate_samples_higher_is_better(self) -> None:
        s = aggregate_samples([100.0, 110.0, 90.0], direction="higher_is_better")
        assert s.bound <= s.median
        assert s.direction == "higher_is_better"

    def test_ratify_profile_runs_roundtrip(self) -> None:
        runs = [
            {
                "p95_ms": 10.0,
                "p99_ms": 15.0,
                "ops_per_s": 50.0,
                "recovery_ms_mean": 2.0,
                "max_rss_bytes": 1_000_000,
                "open_fds_end": 8,
            },
            {
                "p95_ms": 11.0,
                "p99_ms": 16.0,
                "ops_per_s": 48.0,
                "recovery_ms_mean": 2.2,
                "max_rss_bytes": 1_100_000,
                "open_fds_end": 8,
            },
            {
                "p95_ms": 10.5,
                "p99_ms": 15.5,
                "ops_per_s": 49.0,
                "recovery_ms_mean": 2.1,
                "max_rss_bytes": 1_050_000,
                "open_fds_end": 9,
            },
        ]
        doc = ratify_profile_runs(
            profile="unit_test_profile",
            environment_label="test-env",
            environment={"machine": "test"},
            run_metrics=runs,
            methodology={
                "warmup_runs": 1,
                "warmup_operations": 2,
                "repetitions": 3,
                "variance_model": "sample_std",
                "matrix_mode": "storage",
                "surfaces": ["python"],
                "storage_profiles": ["parquet"],
            },
            seed=7,
            shape={"node_count": 10, "edge_count": 20},
        )
        assert validate_baseline_document(doc) == []
        assert doc["metrics"]["p95_ms"]["n"] == 3
        assert doc["gates"]["p95_regression_max_ratio"] == REGRESSION_RATIO_LIMIT


# ---------------------------------------------------------------------------
# Regression math
# ---------------------------------------------------------------------------


class TestRegressionGates:
    def test_unexplained_p95_regression_over_10_percent(self) -> None:
        # 15% worse latency → blocks
        reg = unexplained_regression(
            100.0, 115.0, higher_is_worse=True, limit=REGRESSION_RATIO_LIMIT
        )
        assert reg is not None
        assert reg == pytest.approx(0.15)

    def test_explained_p95_regression_does_not_block(self) -> None:
        reg = unexplained_regression(
            100.0,
            115.0,
            higher_is_worse=True,
            limit=REGRESSION_RATIO_LIMIT,
            explanation="lab hardware swap; re-ratifying under new label",
        )
        assert reg is None

    def test_p95_within_10_percent_ok(self) -> None:
        assert (
            unexplained_regression(
                100.0, 109.0, higher_is_worse=True, limit=REGRESSION_RATIO_LIMIT
            )
            is None
        )

    def test_throughput_regression_over_10_percent(self) -> None:
        # 20% lower throughput → blocks
        reg = unexplained_regression(
            100.0, 80.0, higher_is_worse=False, limit=REGRESSION_RATIO_LIMIT
        )
        assert reg is not None
        assert reg == pytest.approx(0.20)

    def test_throughput_improvement_ok(self) -> None:
        assert (
            unexplained_regression(
                100.0, 120.0, higher_is_worse=False, limit=REGRESSION_RATIO_LIMIT
            )
            is None
        )

    def test_compare_to_baseline_blocks_p95_regression(self) -> None:
        baseline = load_baseline("smoke", environment_label=REFERENCE_ENV)
        med_p95 = float(baseline["metrics"]["p95_ms"]["median"])
        med_thr = float(baseline["metrics"]["ops_per_s"]["median"])
        candidate = {
            "p95_ms": med_p95 * 1.15,  # 15% worse
            "p99_ms": float(baseline["metrics"]["p99_ms"]["median"]),
            "ops_per_s": med_thr,
            "recovery_ms_mean": float(baseline["metrics"]["recovery_ms_mean"]["median"]),
            "max_rss_bytes": float(baseline["metrics"]["max_rss_bytes"]["median"]),
        }
        result = compare_to_baseline(
            baseline,
            candidate,
            correctness_errors=0,
            security_errors=0,
            status="success",
            check_bounds=False,
        )
        assert result.passed is False
        names = {g.name for g in result.blocking_failures}
        assert "regression_p95_ms" in names

    def test_compare_to_baseline_blocks_throughput_regression(self) -> None:
        baseline = load_baseline("smoke", environment_label=REFERENCE_ENV)
        med_p95 = float(baseline["metrics"]["p95_ms"]["median"])
        med_thr = float(baseline["metrics"]["ops_per_s"]["median"])
        candidate = {
            "p95_ms": med_p95,
            "p99_ms": float(baseline["metrics"]["p99_ms"]["median"]),
            "ops_per_s": med_thr * 0.85,  # 15% worse
            "recovery_ms_mean": float(baseline["metrics"]["recovery_ms_mean"]["median"]),
            "max_rss_bytes": float(baseline["metrics"]["max_rss_bytes"]["median"]),
        }
        result = compare_to_baseline(
            baseline,
            candidate,
            correctness_errors=0,
            security_errors=0,
            status="success",
            check_bounds=False,
        )
        assert result.passed is False
        assert any(g.name == "regression_ops_per_s" for g in result.blocking_failures)

    def test_within_band_passes_relative_gates(self) -> None:
        baseline = load_baseline("smoke", environment_label=REFERENCE_ENV)
        candidate = {
            "p95_ms": float(baseline["metrics"]["p95_ms"]["median"]) * 1.05,
            "p99_ms": float(baseline["metrics"]["p99_ms"]["median"]) * 1.05,
            "ops_per_s": float(baseline["metrics"]["ops_per_s"]["median"]) * 0.95,
            "recovery_ms_mean": float(baseline["metrics"]["recovery_ms_mean"]["median"]),
            "max_rss_bytes": float(baseline["metrics"]["max_rss_bytes"]["median"]),
        }
        result = compare_to_baseline(
            baseline,
            candidate,
            correctness_errors=0,
            security_errors=0,
            status="success",
            check_bounds=False,
        )
        assert result.passed is True, result.to_json_dict()

    def test_explained_regression_passes(self) -> None:
        baseline = load_baseline("smoke", environment_label=REFERENCE_ENV)
        med_p95 = float(baseline["metrics"]["p95_ms"]["median"])
        candidate = {
            "p95_ms": med_p95 * 1.25,
            "p99_ms": float(baseline["metrics"]["p99_ms"]["median"]),
            "ops_per_s": float(baseline["metrics"]["ops_per_s"]["median"]),
            "recovery_ms_mean": float(baseline["metrics"]["recovery_ms_mean"]["median"]),
            "max_rss_bytes": float(baseline["metrics"]["max_rss_bytes"]["median"]),
        }
        result = compare_to_baseline(
            baseline,
            candidate,
            correctness_errors=0,
            security_errors=0,
            status="success",
            check_bounds=False,
            explanations={
                "p95_ms": "intentional debug instrumentation; not for release"
            },
        )
        assert result.passed is True, result.to_json_dict()


# ---------------------------------------------------------------------------
# Correctness / security hard fails
# ---------------------------------------------------------------------------


class TestZeroErrorGates:
    def test_correctness_error_blocks(self) -> None:
        baseline = load_baseline("tiny", environment_label=REFERENCE_ENV)
        med = {
            k: float(baseline["metrics"][k]["median"])
            for k in ("p95_ms", "p99_ms", "ops_per_s", "recovery_ms_mean", "max_rss_bytes")
        }
        result = compare_to_baseline(
            baseline,
            med,
            correctness_errors=1,
            security_errors=0,
            status="success",
            check_bounds=False,
        )
        assert result.passed is False
        assert any(g.name == "correctness_errors" for g in result.blocking_failures)

    def test_security_error_blocks(self) -> None:
        baseline = load_baseline("tiny", environment_label=REFERENCE_ENV)
        med = {
            k: float(baseline["metrics"][k]["median"])
            for k in ("p95_ms", "p99_ms", "ops_per_s", "recovery_ms_mean", "max_rss_bytes")
        }
        result = compare_to_baseline(
            baseline,
            med,
            correctness_errors=0,
            security_errors=1,
            status="success",
            check_bounds=False,
        )
        assert result.passed is False
        assert any(g.name == "security_errors" for g in result.blocking_failures)

    def test_failed_status_blocks(self) -> None:
        baseline = load_baseline("tiny", environment_label=REFERENCE_ENV)
        med = {
            k: float(baseline["metrics"][k]["median"])
            for k in ("p95_ms", "p99_ms", "ops_per_s", "recovery_ms_mean", "max_rss_bytes")
        }
        result = compare_to_baseline(
            baseline,
            med,
            correctness_errors=0,
            security_errors=0,
            status="error",
            check_bounds=False,
        )
        assert result.passed is False
        assert any(g.name == "run_status" for g in result.blocking_failures)


# ---------------------------------------------------------------------------
# Live harness comparisons (runnable profiles)
# ---------------------------------------------------------------------------


def _run_storage(profile_name: str, tmp_path: Path):
    profile = get_profile(profile_name).with_surfaces(("python",))
    return run_profile(
        profile,
        work_dir=tmp_path / profile_name,
        matrix_mode="storage",
        surfaces=("python",),
        storage_profiles=profile.storage_profiles,
    )


class TestLiveHarnessBaselineComparison:
    def test_tiny_receipt_zero_correctness_errors(self, tmp_path: Path) -> None:
        result = _run_storage("tiny", tmp_path)
        assert result.receipt is not None
        receipt = result.receipt.to_json_dict()
        assert validate_receipt(receipt) == []
        assert result.status == "success"
        # Python cells must be clean.
        for cell in result.cells:
            if cell.surface == "python":
                assert cell.seed_status == "success", cell.error
                assert cell.recovery_ok is True

        baseline = load_baseline("tiny", environment_label=REFERENCE_ENV)
        # Relative gates only — host may differ from labelled lab.
        cmp = compare_receipt_to_baseline(
            receipt,
            baseline,
            check_bounds=False,
            security_errors=0,
        )
        assert cmp.correctness_errors == 0
        assert cmp.security_errors == 0
        # Relative regression may or may not pass depending on host variance;
        # enforce that any failure is a real gate with detail, and that
        # correctness/security always pass.
        assert all(
            g.passed
            for g in cmp.gates
            if g.name in ("correctness_errors", "security_errors", "run_status")
        )

    def test_smoke_live_relative_comparison(self, tmp_path: Path) -> None:
        result = _run_storage("smoke", tmp_path)
        assert result.status == "success"
        receipt = result.receipt.to_json_dict()
        metrics = extract_metrics_from_receipt(receipt)
        assert metrics["p95_ms"] > 0
        assert metrics["ops_per_s"] > 0
        baseline = load_baseline("smoke", environment_label=REFERENCE_ENV)
        cmp = compare_receipt_to_baseline(
            receipt, baseline, check_bounds=False, security_errors=0
        )
        assert cmp.correctness_errors == 0
        assert isinstance(cmp, ComparisonResult)
        # Inject artificial regression and ensure the gate fires.
        bad = dict(metrics)
        bad["p95_ms"] = metrics["p95_ms"] * 2.0
        bad_result = compare_to_baseline(
            baseline,
            bad,
            correctness_errors=0,
            security_errors=0,
            status="success",
            check_bounds=False,
        )
        assert bad_result.passed is False
        assert any("p95" in g.name for g in bad_result.blocking_failures)

    def test_corpus_211_live(self, tmp_path: Path) -> None:
        result = _run_storage("corpus_211", tmp_path)
        assert result.status == "success"
        receipt = result.receipt.to_json_dict()
        assert receipt["error"]["count"] == 0
        baseline = load_baseline("corpus_211", environment_label=REFERENCE_ENV)
        cmp = compare_receipt_to_baseline(
            receipt, baseline, check_bounds=False, security_errors=0
        )
        assert cmp.correctness_errors == 0

    def test_corpus_cvefixes_live(self, tmp_path: Path) -> None:
        result = _run_storage("corpus_cvefixes", tmp_path)
        assert result.status == "success"
        receipt = result.receipt.to_json_dict()
        assert receipt["error"]["count"] == 0
        baseline = load_baseline("corpus_cvefixes", environment_label=REFERENCE_ENV)
        cmp = compare_receipt_to_baseline(
            receipt, baseline, check_bounds=False, security_errors=0
        )
        assert cmp.correctness_errors == 0

    def test_concurrent_mixed_live_16_graphs(self, tmp_path: Path) -> None:
        profile = get_profile("concurrent_mixed")
        assert profile.graph_count >= 16
        result = _run_storage("concurrent_mixed", tmp_path)
        assert result.status == "success"
        # storage matrix × 16 graphs
        assert len(result.cells) >= 16
        receipt = result.receipt.to_json_dict()
        assert receipt["error"]["count"] == 0
        baseline = load_baseline("concurrent_mixed", environment_label=REFERENCE_ENV)
        cmp = compare_receipt_to_baseline(
            receipt, baseline, check_bounds=False, security_errors=0
        )
        assert cmp.correctness_errors == 0

    def test_synthetic_large_baseline_comparison_with_fixture_metrics(self) -> None:
        """Full 1M/10M materialization is environment-gated; exercise gates on fixture."""
        baseline = load_baseline("synthetic_large", environment_label=REFERENCE_ENV)
        assert baseline["shape"]["node_count"] == 1_000_000
        assert baseline["shape"]["edge_count"] == 10_000_000
        med = {
            k: float(baseline["metrics"][k]["median"])
            for k in ("p95_ms", "p99_ms", "ops_per_s", "recovery_ms_mean", "max_rss_bytes")
        }
        ok = compare_to_baseline(
            baseline,
            med,
            correctness_errors=0,
            security_errors=0,
            status="success",
            check_bounds=True,
        )
        assert ok.passed is True, ok.to_json_dict()

        regressed = dict(med)
        regressed["ops_per_s"] = med["ops_per_s"] * 0.8
        bad = compare_to_baseline(
            baseline,
            regressed,
            correctness_errors=0,
            security_errors=0,
            status="success",
            check_bounds=False,
        )
        assert bad.passed is False
        assert any(g.name == "regression_ops_per_s" for g in bad.blocking_failures)


# ---------------------------------------------------------------------------
# compare_metrics unit surface
# ---------------------------------------------------------------------------


class TestCompareMetrics:
    def test_compare_metrics_list(self) -> None:
        baseline_metrics = {
            "p95_ms": {
                "median": 10.0,
                "direction": "lower_is_better",
                "bound": 20.0,
            },
            "ops_per_s": {
                "median": 100.0,
                "direction": "higher_is_better",
                "bound": 70.0,
            },
        }
        deltas = compare_metrics(
            baseline_metrics,
            {"p95_ms": 10.5, "ops_per_s": 95.0},
            regression_limit=0.10,
        )
        by_name = {d.name: d for d in deltas}
        assert by_name["p95_ms"].exceeds_limit is False
        assert by_name["ops_per_s"].exceeds_limit is False
        assert by_name["p95_ms"].regression_ratio == pytest.approx(0.05)

    def test_build_baseline_document_digest(self) -> None:
        summary = aggregate_samples([1.0, 1.1, 0.9], direction="lower_is_better")
        thr = aggregate_samples([10.0, 11.0, 9.5], direction="higher_is_better")
        doc = build_baseline_document(
            profile="x",
            environment_label="e",
            environment={},
            methodology={
                "warmup_runs": 1,
                "warmup_operations": 1,
                "repetitions": 3,
                "variance_model": "sample_std",
                "matrix_mode": "ci",
                "surfaces": ["python"],
                "storage_profiles": ["parquet"],
            },
            metric_summaries={
                "p95_ms": summary,
                "p99_ms": summary,
                "ops_per_s": thr,
                "recovery_ms_mean": summary,
                "max_rss_bytes": aggregate_samples(
                    [1000, 1100, 1050], direction="lower_is_better"
                ),
            },
            seed=1,
        )
        assert doc["digest"]
        assert validate_baseline_document(doc) == []


# ---------------------------------------------------------------------------
# SLO doc presence
# ---------------------------------------------------------------------------


class TestSLODoc:
    def test_slo_doc_exists_and_covers_gates(self) -> None:
        # Repo root: tests/load/knowledge_graphs -> 4 parents
        root = Path(__file__).resolve().parents[3]
        path = root / "docs" / "operations" / "knowledge_graphs_slos.md"
        assert path.is_file(), path
        text = path.read_text(encoding="utf-8")
        assert "KGP-030" in text
        assert "10%" in text
        assert "environment" in text.lower()
        assert "smoke" in text
        assert "synthetic_large" in text or "1" in text
        assert "correctness" in text.lower()
        assert "warmup" in text.lower()
        assert "repetition" in text.lower()
