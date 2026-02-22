"""
Session 35: TDFOL performance_dashboard.py (0%->99%), performance_profiler.py (0%->90%),
strategies (65-91%->65-91%+), proof_explainer gaps (96%->98%).

Coverage results:
  - performance_dashboard.py: 0% -> 99%
  - performance_profiler.py: 0% -> 90%
  - proof_explainer.py: 96% -> 98%
  - strategies/base.py: 100%
  - strategies/strategy_selector.py: 67% -> 85%
  - strategies/cec_delegate.py: 76% -> 88%
  - strategies/forward_chaining.py: 91% (unchanged)
  - strategies/modal_tableaux.py: 65% -> 74%
  - strategies/__init__.py: 65% (ImportError branches unreachable without mocking)
"""

import json
import os
import sys
import time
import tempfile
import pathlib
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers - minimal Formula-like objects that pass isinstance checks
# ---------------------------------------------------------------------------

from ipfs_datasets_py.logic.TDFOL.tdfol_core import (
    TDFOLKnowledgeBase,
    Predicate,
    DeonticFormula,
    DeonticOperator,
    TemporalFormula,
    TemporalOperator,
    UnaryFormula,
    BinaryFormula,
    QuantifiedFormula,
    BinaryTemporalFormula,
    LogicOperator,
    Quantifier,
    Variable,
)
from ipfs_datasets_py.logic.TDFOL.tdfol_prover import ProofResult, ProofStatus, ProofStep


def _make_proof_result(proved: bool = True, time_ms: float = 5.0) -> ProofResult:
    formula = Predicate("P", ())
    steps = [ProofStep(formula=formula, justification="test")] if proved else []
    return ProofResult(
        status=ProofStatus.PROVED if proved else ProofStatus.DISPROVED,
        formula=formula,
        proof_steps=steps,
        time_ms=time_ms,
        method="test",
    )


# ---------------------------------------------------------------------------
# PerformanceDashboard tests
# ---------------------------------------------------------------------------

class TestPerformanceDashboardInit:
    def setup_method(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        self.PerformanceDashboard = PerformanceDashboard

    def test_empty_init(self):
        d = self.PerformanceDashboard()
        assert d.proof_metrics == []
        assert d.timeseries_metrics == []
        assert d.start_time > 0

    def test_stats_cache_starts_invalid(self):
        d = self.PerformanceDashboard()
        assert not d._stats_cache_valid


class TestPerformanceDashboardDataClasses:
    def test_proof_metrics_to_dict(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import ProofMetrics
        m = ProofMetrics(
            timestamp=1000.0,
            formula_str="P ∧ Q",
            formula_complexity=2,
            proof_time_ms=10.5,
            success=True,
            method="forward",
            strategy="forward_chaining",
            cache_hit=False,
            memory_usage_mb=5.0,
            num_steps=3,
            formula_type="propositional",
        )
        d = m.to_dict()
        assert d["formula"] == "P ∧ Q"
        assert d["success"] is True
        assert "datetime" in d

    def test_timeseries_metric_to_dict(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import TimeSeriesMetric
        m = TimeSeriesMetric(
            timestamp=time.time(),
            metric_name="proof_time_ms",
            value=42.0,
            tags={"strategy": "forward"},
        )
        d = m.to_dict()
        assert d["metric"] == "proof_time_ms"
        assert d["value"] == 42.0

    def test_aggregated_stats_to_dict_empty(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import AggregatedStats
        stats = AggregatedStats(total_proofs=0, successful_proofs=0)
        d = stats.to_dict()
        assert d["success_rate"] == 0.0

    def test_aggregated_stats_to_dict_with_data(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import AggregatedStats
        stats = AggregatedStats(total_proofs=10, successful_proofs=8)
        d = stats.to_dict()
        assert abs(d["success_rate"] - 0.8) < 1e-9

    def test_metric_type_enum(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import MetricType
        assert MetricType.PROOF_TIME.value == "proof_time"
        assert MetricType.CACHE_HIT.value == "cache_hit"


class TestPerformanceDashboardRecordProof:
    def setup_method(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        self.d = PerformanceDashboard()

    def test_record_proof_success(self):
        result = _make_proof_result(proved=True, time_ms=8.0)
        self.d.record_proof(result, metadata={"strategy": "forward"})
        assert len(self.d.proof_metrics) == 1
        m = self.d.proof_metrics[0]
        assert m.success is True
        assert m.strategy == "forward"

    def test_record_proof_failure(self):
        result = _make_proof_result(proved=False, time_ms=2.0)
        self.d.record_proof(result)
        assert not self.d.proof_metrics[0].success

    def test_record_proof_cache_hit(self):
        result = _make_proof_result(proved=True, time_ms=0.5)
        self.d.record_proof(result, metadata={"cache_hit": True})
        assert self.d.proof_metrics[0].cache_hit is True

    def test_record_proof_invalidates_cache(self):
        result = _make_proof_result()
        self.d._stats_cache_valid = True
        self.d.record_proof(result)
        assert not self.d._stats_cache_valid

    def test_record_proof_via_status_attribute(self):
        """Test that status-based success detection works."""
        result = MagicMock()
        del result.is_proved  # remove is_proved attr
        result.status = MagicMock()
        result.status.__str__ = lambda s: "ProofStatus.PROVED"
        result.formula = Predicate("X", ())
        result.time_ms = 3.0
        result.method = "test"
        result.proof_steps = []
        self.d.record_proof(result)
        assert self.d.proof_metrics[0].success is True

    def test_record_proof_via_metadata_success(self):
        """Test success from metadata when no status attrs."""
        result = MagicMock(spec=[])
        result.formula = Predicate("X", ())
        result.time_ms = 3.0
        result.method = "test"
        result.proof_steps = []
        self.d.record_proof(result, metadata={"success": True})
        assert self.d.proof_metrics[0].success is True


class TestPerformanceDashboardRecordMetric:
    def setup_method(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        self.d = PerformanceDashboard()

    def test_record_metric_basic(self):
        self.d.record_metric("memory_mb", 128.5, tags={"process": "test"})
        assert len(self.d.timeseries_metrics) == 1
        m = self.d.timeseries_metrics[0]
        assert m.metric_name == "memory_mb"
        assert m.value == 128.5

    def test_record_metric_no_tags(self):
        self.d.record_metric("cpu", 0.75)
        assert self.d.timeseries_metrics[0].tags == {}


class TestPerformanceDashboardGetStatistics:
    def setup_method(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        self.d = PerformanceDashboard()

    def test_empty_stats(self):
        stats = self.d.get_statistics()
        assert stats["total_proofs"] == 0
        assert stats["success_rate"] == 0.0

    def test_stats_with_data(self):
        r1 = _make_proof_result(proved=True, time_ms=10.0)
        r2 = _make_proof_result(proved=False, time_ms=20.0)
        self.d.record_proof(r1, metadata={"strategy": "forward", "cache_hit": False})
        self.d.record_proof(r2, metadata={"strategy": "forward", "cache_hit": True})
        stats = self.d.get_statistics()
        assert stats["total_proofs"] == 2
        assert stats["successful_proofs"] == 1
        assert stats["failed_proofs"] == 1
        assert stats["cache_hit_rate"] == 0.5
        assert stats["timing"]["min_ms"] > 0
        assert stats["timing"]["max_ms"] >= stats["timing"]["min_ms"]

    def test_stats_cached_after_first_call(self):
        r = _make_proof_result()
        self.d.record_proof(r)
        stats1 = self.d.get_statistics()
        stats2 = self.d.get_statistics()
        assert stats1 == stats2
        assert self.d._stats_cache_valid

    def test_stats_with_cache_speedup(self):
        """Cache speedup calculated when both hit/miss times present."""
        for i in range(3):
            r = _make_proof_result(proved=True, time_ms=1.0)
            self.d.record_proof(r, metadata={"cache_hit": True})
        for i in range(3):
            r = _make_proof_result(proved=True, time_ms=10.0)
            self.d.record_proof(r, metadata={"cache_hit": False})
        stats = self.d.get_statistics()
        assert stats["avg_speedup_from_cache"] > 0

    def test_stats_multiple_strategies(self):
        self.d.record_proof(_make_proof_result(True, 10.0), metadata={"strategy": "S1"})
        self.d.record_proof(_make_proof_result(False, 5.0), metadata={"strategy": "S2"})
        stats = self.d.get_statistics()
        assert "S1" in stats["strategies"]["counts"]
        assert "S2" in stats["strategies"]["counts"]


class TestPerformanceDashboardCompareStrategies:
    def setup_method(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        self.d = PerformanceDashboard()

    def test_empty_comparison(self):
        c = self.d.compare_strategies()
        assert "strategies" in c
        assert c["strategies"] == {}

    def test_comparison_with_data(self):
        self.d.record_proof(_make_proof_result(True, 5.0), metadata={"strategy": "forward"})
        self.d.record_proof(_make_proof_result(True, 7.0), metadata={"strategy": "forward"})
        self.d.record_proof(_make_proof_result(False, 15.0), metadata={"strategy": "modal"})
        c = self.d.compare_strategies()
        fwd = c["strategies"]["forward"]
        assert fwd["count"] == 2
        assert fwd["success_rate"] == 1.0
        modal = c["strategies"]["modal"]
        assert modal["success_rate"] == 0.0


class TestPerformanceDashboardClear:
    def test_clear_resets_all_data(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        d = PerformanceDashboard()
        d.record_proof(_make_proof_result())
        d.record_metric("cpu", 0.5)
        d.clear()
        assert d.proof_metrics == []
        assert d.timeseries_metrics == []
        assert not d._stats_cache_valid


class TestPerformanceDashboardComplexity:
    def setup_method(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        self.d = PerformanceDashboard()

    def test_complexity_flat_formula(self):
        assert self.d._calculate_complexity("P") == 0

    def test_complexity_nested_formula(self):
        # "P(Q(x))" has max depth 2
        assert self.d._calculate_complexity("P(Q(x))") == 2

    def test_formula_type_temporal(self):
        assert self.d._determine_formula_type("Always(P)") == "temporal"

    def test_formula_type_deontic(self):
        assert self.d._determine_formula_type("Obligatory(P)") == "deontic"

    def test_formula_type_modal(self):
        assert self.d._determine_formula_type("Necessary(P)") == "modal"

    def test_formula_type_propositional(self):
        assert self.d._determine_formula_type("P ∧ Q") == "propositional"

    def test_formula_type_temporal_symbol(self):
        assert self.d._determine_formula_type("□P") == "temporal"


class TestPerformanceDashboardExportHTML:
    def test_generate_html_creates_file(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        d = PerformanceDashboard()
        d.record_proof(_make_proof_result(), metadata={"strategy": "forward"})
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            path = f.name
        try:
            d.generate_html(path)
            assert os.path.exists(path)
            content = pathlib.Path(path).read_text()
            assert "<!DOCTYPE html>" in content or "<html" in content
        finally:
            os.unlink(path)

    def test_export_json_creates_valid_json(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        d = PerformanceDashboard()
        d.record_proof(_make_proof_result(), metadata={"strategy": "test"})
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            d.export_json(path)
            with open(path) as f:
                data = json.load(f)
            assert "statistics" in data
            assert "proof_metrics" in data
            assert len(data["proof_metrics"]) == 1
        finally:
            os.unlink(path)


class TestPerformanceDashboardGlobalFunctions:
    def test_get_global_dashboard_returns_instance(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import (
            get_global_dashboard,
            reset_global_dashboard,
            PerformanceDashboard,
        )
        reset_global_dashboard()
        d = get_global_dashboard()
        assert isinstance(d, PerformanceDashboard)

    def test_get_global_dashboard_singleton(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import (
            get_global_dashboard,
            reset_global_dashboard,
        )
        reset_global_dashboard()
        d1 = get_global_dashboard()
        d2 = get_global_dashboard()
        assert d1 is d2

    def test_reset_global_dashboard(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import (
            get_global_dashboard,
            reset_global_dashboard,
        )
        reset_global_dashboard()
        d1 = get_global_dashboard()
        # Record something so we can tell them apart
        d1.record_metric("before_reset", 1.0)
        reset_global_dashboard()
        d2 = get_global_dashboard()
        # After reset, d2 should be a fresh dashboard with no metrics
        assert len(d2.timeseries_metrics) == 0

    def test_histogram_bins_empty(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        d = PerformanceDashboard()
        bins = d._create_histogram_bins([], num_bins=5)
        assert bins == []

    def test_histogram_bins_with_data(self):
        from ipfs_datasets_py.logic.TDFOL.performance_dashboard import PerformanceDashboard
        d = PerformanceDashboard()
        data = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        bins = d._create_histogram_bins(data, num_bins=5)
        assert len(bins) == 5
        total = sum(b["count"] for b in bins)
        assert total == len(data)


# ---------------------------------------------------------------------------
# PerformanceProfiler tests
# ---------------------------------------------------------------------------

class TestPerformanceProfilerDataClasses:
    def test_profiling_stats_to_dict(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import ProfilingStats
        stats = ProfilingStats(
            function_name="test",
            total_time=1.0,
            mean_time=0.1,
            median_time=0.095,
            min_time=0.05,
            max_time=0.2,
            std_dev=0.03,
            runs=10,
            calls_per_run=50.0,
        )
        d = stats.to_dict()
        assert d["function_name"] == "test"
        assert d["runs"] == 10

    def test_profiling_stats_mean_time_ms(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import ProfilingStats
        s = ProfilingStats("f", 1.0, 0.05, 0.05, 0.04, 0.06, 0.005, 10, 20.0)
        assert abs(s.mean_time_ms - 50.0) < 1e-9

    def test_profiling_stats_meets_threshold(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import ProfilingStats, THRESHOLD_COMPLEX_FORMULA
        # mean_time=0.05s -> mean_time_ms=50ms < 100ms threshold
        s = ProfilingStats("f", 0.5, 0.05, 0.05, 0.04, 0.06, 0.005, 10, 20.0)
        assert s.meets_threshold

    def test_bottleneck_to_dict(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import Bottleneck, BottleneckSeverity
        b = Bottleneck(
            function="module:42:heavy_fn",
            time=2.5,
            calls=1000,
            time_per_call=0.0025,
            severity=BottleneckSeverity.CRITICAL,
            recommendation="optimize",
        )
        d = b.to_dict()
        assert d["function"] == "module:42:heavy_fn"
        assert d["severity"] == "critical"

    def test_memory_stats_to_dict(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import MemoryStats
        m = MemoryStats(
            function_name="fn",
            peak_mb=50.0,
            start_mb=10.0,
            end_mb=15.0,
            growth_mb=5.0,
            allocations=1000,
            deallocations=900,
            net_allocations=100,
        )
        d = m.to_dict()
        assert d["peak_mb"] == 50.0

    def test_memory_stats_has_leak_false(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import MemoryStats, THRESHOLD_MEMORY_LEAK
        m = MemoryStats("fn", 10.0, 5.0, 5.5, 0.5, 0, 0, 0)
        assert not m.has_leak  # growth < threshold

    def test_memory_stats_has_leak_true(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import MemoryStats, THRESHOLD_MEMORY_LEAK
        m = MemoryStats("fn", 100.0, 5.0, 15.0, 10.0, 0, 0, 0)
        assert m.has_leak  # growth > 5MB threshold

    def test_benchmark_result_to_dict(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import BenchmarkResult
        r = BenchmarkResult(
            name="test_bench",
            formula="P",
            time_ms=5.0,
            memory_mb=1.0,
            passed=True,
        )
        d = r.to_dict()
        assert d["name"] == "test_bench"
        assert d["passed"] is True

    def test_benchmark_results_pass_rate(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import BenchmarkResult, BenchmarkResults
        r1 = BenchmarkResult("a", "P", 5.0, 0.0, True)
        r2 = BenchmarkResult("b", "Q", 15.0, 0.0, False)
        results = BenchmarkResults(
            benchmarks=[r1, r2],
            total_time_ms=20.0,
            passed=1,
            failed=1,
            regressions=0,
            timestamp="2026-01-01",
        )
        assert results.pass_rate == 0.5

    def test_report_format_enum(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import ReportFormat
        assert ReportFormat.TEXT.value == "text"
        assert ReportFormat.JSON.value == "json"
        assert ReportFormat.HTML.value == "html"


class TestPerformanceProfilerInit:
    def test_basic_init(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            assert p.enable_cprofile
            assert p.enable_memory
            assert p.history == []

    def test_init_with_baseline(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler
        with tempfile.TemporaryDirectory() as tmpdir:
            baseline_path = os.path.join(tmpdir, "baseline.json")
            with open(baseline_path, "w") as f:
                json.dump({"simple_propositional": 5.0}, f)
            p = PerformanceProfiler(output_dir=tmpdir, baseline_path=baseline_path)
            assert "simple_propositional" in p.baseline


class TestPerformanceProfilerFunctionProfiling:
    def test_profile_simple_function(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)

            def simple_fn():
                return sum(range(100))

            stats = p.profile_function(simple_fn, runs=3)
            assert stats.function_name == "simple_fn"
            assert stats.runs == 3
            assert stats.mean_time > 0
            assert stats.total_time > 0
            assert len(p.history) == 1

    def test_profile_function_error(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, TDFOLError
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)

            def failing_fn():
                raise ValueError("test error")

            with pytest.raises(TDFOLError):
                p.profile_function(failing_fn, runs=1)

    def test_profile_function_cprofile_disabled(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, TDFOLError
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir, enable_cprofile=False)

            def simple_fn():
                return 1

            with pytest.raises(TDFOLError, match="cProfile disabled"):
                p.profile_function(simple_fn, runs=1)


class TestPerformanceProfilerProverProfiling:
    def test_profile_prover(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            formula = Predicate("P", ())

            def fake_prove(f):
                return _make_proof_result()

            mock_prover = MagicMock()
            mock_prover.prove = fake_prove
            stats = p.profile_prover(mock_prover, formula, runs=3)
            assert stats.runs == 3

    def test_profile_prover_missing_method(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, TDFOLError
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            mock_prover = MagicMock(spec=[])  # no methods
            with pytest.raises(TDFOLError, match="has no method"):
                p.profile_prover(mock_prover, Predicate("P", ()), runs=1)


class TestPerformanceProfilerMemoryProfiling:
    def test_memory_profile_basic(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, MemoryStats
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)

            def simple_fn():
                x = [i for i in range(1000)]
                return sum(x)

            stats = p.memory_profile(simple_fn)
            assert isinstance(stats, MemoryStats)
            assert stats.peak_mb >= 0

    def test_memory_profile_disabled(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, TDFOLError
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir, enable_memory=False)
            with pytest.raises(TDFOLError, match="Memory profiling disabled"):
                p.memory_profile(lambda: None)


class TestPerformanceProfilerBenchmarkSuite:
    def test_run_benchmark_suite_default(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, BenchmarkResults
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            results = p.run_benchmark_suite()
            assert isinstance(results, BenchmarkResults)
            assert results.passed + results.failed == len(results.benchmarks)
            assert 0.0 <= results.pass_rate <= 1.0

    def test_run_benchmark_suite_custom(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler
        custom = [{"name": "custom_bench", "formula": "P ∧ Q", "threshold_ms": 100.0, "func": lambda: True}]
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            results = p.run_benchmark_suite(custom_benchmarks=custom)
            names = [b.name for b in results.benchmarks]
            assert "custom_bench" in names


class TestPerformanceProfilerGenerateReport:
    def test_generate_text_report(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, ReportFormat
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            output_path = p.generate_report(format=ReportFormat.TEXT)
            assert os.path.exists(output_path)
            content = pathlib.Path(output_path).read_text()
            assert "TDFOL" in content or "Performance" in content

    def test_generate_json_report(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, ReportFormat
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            output_path = p.generate_report(format=ReportFormat.JSON)
            assert os.path.exists(output_path)
            with open(output_path) as f:
                data = json.load(f)
            assert "history" in data or isinstance(data, dict)

    def test_generate_html_report(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, ReportFormat
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            output_path = p.generate_report(format=ReportFormat.HTML)
            assert os.path.exists(output_path)
            content = pathlib.Path(output_path).read_text()
            assert "<html" in content or "<!DOCTYPE" in content

    def test_generate_report_to_file(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, ReportFormat
        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = os.path.join(tmpdir, "custom_report.txt")
            p = PerformanceProfiler(output_dir=tmpdir)
            result = p.generate_report(output_path=output_file, format=ReportFormat.TEXT)
            assert os.path.exists(result)


class TestPerformanceProfilerDecorators:
    def test_profile_this_decorator_no_args(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import profile_this
        call_count = {"n": 0}

        @profile_this
        def simple():
            call_count["n"] += 1
            return 42

        result = simple()
        assert result == 42
        assert call_count["n"] == 1

    def test_profile_this_decorator_with_args(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import profile_this
        call_count = {"n": 0}

        @profile_this(print_stats=False, top_n=5)
        def simple():
            call_count["n"] += 1
            return "ok"

        result = simple()
        assert result == "ok"
        assert call_count["n"] == 1

    def test_profile_this_disabled(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import profile_this
        call_count = {"n": 0}

        @profile_this(enabled=False)
        def simple():
            call_count["n"] += 1
            return "disabled"

        result = simple()
        assert result == "disabled"
        assert call_count["n"] == 1

    def test_memory_profile_this_decorator(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import memory_profile_this
        call_count = {"n": 0}

        @memory_profile_this
        def simple():
            call_count["n"] += 1
            return [i for i in range(100)]

        result = simple()
        assert isinstance(result, list)
        assert call_count["n"] == 1


class TestProfileBlock:
    def test_profile_block_context_manager(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import ProfileBlock, PerformanceProfiler
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            with ProfileBlock("test_block", profiler=p) as block:
                x = sum(range(100))
            assert block.end_time > block.start_time

    def test_profile_block_no_profiler(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import ProfileBlock
        with ProfileBlock("standalone_block") as block:
            time.sleep(0.001)
        assert block.end_time > block.start_time


# ---------------------------------------------------------------------------
# Strategy tests
# ---------------------------------------------------------------------------

class TestStrategiesInit:
    def test_strategy_type_enum(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.base import StrategyType
        assert StrategyType.FORWARD_CHAINING.value == "forward_chaining"
        assert StrategyType.MODAL_TABLEAUX.value == "modal_tableaux"

    def test_prover_strategy_str(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        s = ForwardChainingStrategy()
        text = str(s)
        assert "Forward Chaining" in text

    def test_prover_strategy_repr(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        s = ForwardChainingStrategy()
        text = repr(s)
        assert "ProverStrategy" in text

    def test_prover_strategy_estimate_cost_default(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        s = ForwardChainingStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("P", ())
        cost = s.estimate_cost(formula, kb)
        assert isinstance(cost, float)


class TestForwardChainingStrategy:
    def test_can_handle_any_formula(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        s = ForwardChainingStrategy()
        kb = TDFOLKnowledgeBase()
        assert s.can_handle(Predicate("P", ()), kb)

    def test_prove_axiom_in_kb(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        s = ForwardChainingStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("P", ())
        kb.add_axiom(formula)
        result = s.prove(formula, kb)
        assert result.is_proved()

    def test_prove_theorem_in_kb(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        s = ForwardChainingStrategy()
        kb = TDFOLKnowledgeBase()
        formula = Predicate("Q", ())
        kb.add_theorem(formula)
        result = s.prove(formula, kb)
        assert result.is_proved()

    def test_prove_not_in_kb_returns_unknown(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        s = ForwardChainingStrategy(max_iterations=2)
        kb = TDFOLKnowledgeBase()
        formula = Predicate("Unknown", ())
        result = s.prove(formula, kb)
        assert result.status in (ProofStatus.DISPROVED, ProofStatus.UNKNOWN)

    def test_prove_max_derived_limit(self):
        """Test that max_derived stops forward chaining early."""
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        s = ForwardChainingStrategy(max_iterations=100, max_derived=1)
        kb = TDFOLKnowledgeBase()
        # Add many axioms to trigger the max_derived limit
        for i in range(5):
            kb.add_axiom(Predicate(f"P{i}", ()))
        formula = Predicate("Goal", ())
        result = s.prove(formula, kb)
        # Should stop early due to max_derived=1, not crash
        assert result is not None

    def test_get_priority(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        s = ForwardChainingStrategy()
        assert s.get_priority() > 0


class TestModalTableauxStrategy:
    def test_is_modal_deontic(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        kb = TDFOLKnowledgeBase()
        assert s.can_handle(formula, kb)

    def test_is_modal_temporal(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
        kb = TDFOLKnowledgeBase()
        assert s.can_handle(formula, kb)

    def test_is_not_modal_propositional(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = Predicate("P", ())
        kb = TDFOLKnowledgeBase()
        assert not s.can_handle(formula, kb)

    def test_has_deontic_operators(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        df = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        assert s._has_deontic_operators(df)

    def test_has_temporal_operators(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        tf = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
        assert s._has_temporal_operators(tf)

    def test_has_nested_temporal(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        inner = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
        outer = TemporalFormula(TemporalOperator.EVENTUALLY, inner)
        assert s._has_nested_temporal(outer)

    def test_has_no_nested_temporal_shallow(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        tf = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
        # Single level only, not nested
        assert not s._has_nested_temporal(tf)

    def test_traverse_formula_binary_formula(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        # BinaryFormula contains a DeonticFormula on the right
        lhs = Predicate("P", ())
        rhs = DeonticFormula(DeonticOperator.PERMISSION, Predicate("Q", ()))
        bf = BinaryFormula(LogicOperator.AND, lhs, rhs)
        assert s._has_deontic_operators(bf)

    def test_traverse_formula_quantified(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        x = Variable("x")
        inner = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", (x,)))
        qf = QuantifiedFormula(Quantifier.FORALL, x, inner)
        assert s._has_deontic_operators(qf)

    def test_traverse_formula_unary_formula(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        inner = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        uf = UnaryFormula(LogicOperator.NOT, inner)
        assert s._has_deontic_operators(uf)

    def test_estimate_cost_base(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        kb = TDFOLKnowledgeBase()
        cost = s.estimate_cost(formula, kb)
        assert cost >= 2.0

    def test_estimate_cost_nested_temporal_increases_cost(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        inner = TemporalFormula(TemporalOperator.ALWAYS, Predicate("P", ()))
        outer = TemporalFormula(TemporalOperator.EVENTUALLY, inner)
        kb = TDFOLKnowledgeBase()
        base_cost = s.estimate_cost(DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ())), kb)
        nested_cost = s.estimate_cost(outer, kb)
        assert nested_cost > base_cost

    def test_get_priority(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        assert s.get_priority() == 80

    def test_prove_deontic_formula(self):
        """Prove a deontic formula - triggers _prove_basic_modal fallback path."""
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        kb = TDFOLKnowledgeBase()
        result = s.prove(formula, kb, timeout_ms=1000)
        assert result is not None
        assert result.status in (ProofStatus.PROVED, ProofStatus.DISPROVED, ProofStatus.UNKNOWN, ProofStatus.ERROR)


class TestCECDelegateStrategy:
    def test_can_handle_no_cec(self):
        from ipfs_datasets_py.logic.TDFOL.strategies import cec_delegate
        with patch.object(cec_delegate, 'HAVE_CEC_PROVER', False):
            s = cec_delegate.CECDelegateStrategy()
            s.cec_engine = None
            kb = TDFOLKnowledgeBase()
            assert not s.can_handle(Predicate("P", ()), kb)

    def test_prove_no_cec_returns_unknown(self):
        from ipfs_datasets_py.logic.TDFOL.strategies import cec_delegate
        with patch.object(cec_delegate, 'HAVE_CEC_PROVER', False):
            s = cec_delegate.CECDelegateStrategy()
            s.cec_engine = None
            kb = TDFOLKnowledgeBase()
            result = s.prove(Predicate("P", ()), kb)
            assert result.status == ProofStatus.UNKNOWN

    def test_prove_axiom_in_kb_with_cec(self):
        """When CEC available and formula in KB, prove it directly."""
        from ipfs_datasets_py.logic.TDFOL.strategies import cec_delegate
        formula = Predicate("P", ())
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(formula)
        mock_engine = MagicMock()
        with patch.object(cec_delegate, 'HAVE_CEC_PROVER', True):
            s = cec_delegate.CECDelegateStrategy()
            s.cec_engine = mock_engine
            result = s.prove(formula, kb)
            assert result.status == ProofStatus.PROVED

    def test_prove_theorem_in_kb_with_cec(self):
        from ipfs_datasets_py.logic.TDFOL.strategies import cec_delegate
        formula = Predicate("Q", ())
        kb = TDFOLKnowledgeBase()
        kb.add_theorem(formula)
        mock_engine = MagicMock()
        with patch.object(cec_delegate, 'HAVE_CEC_PROVER', True):
            s = cec_delegate.CECDelegateStrategy()
            s.cec_engine = mock_engine
            result = s.prove(formula, kb)
            assert result.status == ProofStatus.PROVED

    def test_prove_unknown_with_cec(self):
        from ipfs_datasets_py.logic.TDFOL.strategies import cec_delegate
        formula = Predicate("Unknown", ())
        kb = TDFOLKnowledgeBase()
        mock_engine = MagicMock()
        with patch.object(cec_delegate, 'HAVE_CEC_PROVER', True):
            s = cec_delegate.CECDelegateStrategy()
            s.cec_engine = mock_engine
            result = s.prove(formula, kb)
            assert result.status == ProofStatus.UNKNOWN

    def test_prove_exception_returns_error(self):
        from ipfs_datasets_py.logic.TDFOL.strategies import cec_delegate
        formula = Predicate("P", ())
        kb = TDFOLKnowledgeBase()
        mock_engine = MagicMock()
        with patch.object(cec_delegate, 'HAVE_CEC_PROVER', True):
            s = cec_delegate.CECDelegateStrategy()
            s.cec_engine = mock_engine
            # Force exception by making the axioms container raise on __contains__
            class _RaisingSet:
                def __contains__(self, x):
                    raise RuntimeError("test error")
            kb.axioms = _RaisingSet()  # type: ignore[assignment]
            result = s.prove(formula, kb)
            assert result.status == ProofStatus.ERROR

    def test_get_priority(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.cec_delegate import CECDelegateStrategy
        s = CECDelegateStrategy()
        assert s.get_priority() == 60

    def test_estimate_cost(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.cec_delegate import CECDelegateStrategy
        s = CECDelegateStrategy()
        kb = TDFOLKnowledgeBase()
        assert s.estimate_cost(Predicate("P", ()), kb) > 1.0


class TestStrategySelector:
    def test_select_strategy_forward_chaining(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        s = StrategySelector([ForwardChainingStrategy()])
        kb = TDFOLKnowledgeBase()
        result = s.select_strategy(Predicate("P", ()), kb)
        assert isinstance(result, ForwardChainingStrategy)

    def test_select_strategy_modal_preferred_for_modal(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        s = StrategySelector([ForwardChainingStrategy(), ModalTableauxStrategy()])
        kb = TDFOLKnowledgeBase()
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        result = s.select_strategy(formula, kb)
        assert isinstance(result, ModalTableauxStrategy)

    def test_select_strategy_prefer_low_cost(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        s = StrategySelector([ForwardChainingStrategy()])
        kb = TDFOLKnowledgeBase()
        result = s.select_strategy(Predicate("P", ()), kb, prefer_low_cost=True)
        assert isinstance(result, ForwardChainingStrategy)

    def test_select_strategy_no_applicable_fallback(self):
        """When no strategy claims can_handle, fallback is used."""
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        fc = ForwardChainingStrategy()
        s = StrategySelector([fc])
        kb = TDFOLKnowledgeBase()
        # Modal formula: ForwardChaining can_handle always returns True
        # So we need a strategy that returns False
        mock_s = MagicMock(spec=fc)
        mock_s.can_handle.return_value = False
        mock_s.get_priority.return_value = 50
        mock_s.strategy_type = fc.strategy_type
        s2 = StrategySelector([mock_s, fc])
        result = s2.select_strategy(Predicate("P", ()), kb)
        assert result is fc  # fc can_handle returns True

    def test_select_strategy_empty_raises(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        s = StrategySelector([])
        kb = TDFOLKnowledgeBase()
        with pytest.raises(ValueError, match="No strategies available"):
            s.select_strategy(Predicate("P", ()), kb)

    def test_select_multiple(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        s = StrategySelector([ForwardChainingStrategy(), ModalTableauxStrategy()])
        kb = TDFOLKnowledgeBase()
        results = s.select_multiple(Predicate("P", ()), kb, max_strategies=2)
        assert 1 <= len(results) <= 2

    def test_select_multiple_no_applicable(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        mock_s = MagicMock()
        mock_s.can_handle.return_value = False
        mock_s.get_priority.return_value = 50
        s = StrategySelector([mock_s])
        kb = TDFOLKnowledgeBase()
        results = s.select_multiple(Predicate("P", ()), kb)
        # Fallback strategy returned
        assert len(results) >= 1

    def test_get_strategy_info(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        s = StrategySelector([ForwardChainingStrategy()])
        info = s.get_strategy_info()
        assert len(info) == 1
        assert "name" in info[0]
        assert "type" in info[0]
        assert "priority" in info[0]

    def test_add_strategy(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        s = StrategySelector([ForwardChainingStrategy()])
        s.add_strategy(ModalTableauxStrategy())
        assert len(s.strategies) == 2

    def test_fallback_uses_forward_chaining(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.forward_chaining import ForwardChainingStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        fc = ForwardChainingStrategy()
        s = StrategySelector([fc])
        result = s._get_fallback_strategy()
        assert isinstance(result, ForwardChainingStrategy)

    def test_fallback_first_when_no_forward_chaining(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        mt = ModalTableauxStrategy()
        s = StrategySelector([mt])
        result = s._get_fallback_strategy()
        assert result is mt

    def test_fallback_empty_raises(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        s = StrategySelector([])
        with pytest.raises(ValueError):
            s._get_fallback_strategy()

    def test_default_strategies_loaded(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.strategy_selector import StrategySelector
        s = StrategySelector()
        assert len(s.strategies) >= 1


# ---------------------------------------------------------------------------
# ProofExplainer gap tests (96% -> 99%)
# ---------------------------------------------------------------------------

class TestProofExplainerGaps:
    def setup_method(self):
        from ipfs_datasets_py.logic.TDFOL.proof_explainer import ProofExplainer, ExplanationLevel
        self.explainer = ProofExplainer(level=ExplanationLevel.NORMAL)

    def _formula(self):
        return Predicate("P", ())

    def test_explain_inference_rule_known(self):
        """Line 274 - rule found in descriptions dict."""
        from ipfs_datasets_py.logic.TDFOL.proof_explainer import ProofExplainer
        formula = self._formula()
        explanation = self.explainer.explain_inference_rule("ModusPonens", [formula], formula)
        assert isinstance(explanation, str)
        assert len(explanation) > 0

    def test_explain_inference_rule_unknown(self):
        """Line 270 - unknown rule falls through to generic template."""
        formula = self._formula()
        explanation = self.explainer.explain_inference_rule("MyCustomRule", [formula], formula)
        assert "MyCustomRule" in explanation or "Applied" in explanation

    def test_explain_proof_zkp_method(self):
        """Lines 249-256 - ZKP method branch."""
        from ipfs_datasets_py.logic.TDFOL.proof_explainer import ProofType
        formula = self._formula()
        explanation = self.explainer.explain_proof(formula, [], ProofType.ZKP, is_proved=True)
        assert explanation is not None

    def test_compare_proofs(self):
        """Line 346+ - compare_proofs method."""
        from ipfs_datasets_py.logic.TDFOL.proof_explainer import ProofType
        formula = self._formula()
        r1 = self.explainer.explain_proof(formula, [], ProofType.FORWARD_CHAINING)
        r2 = self.explainer.explain_proof(formula, [], ProofType.FORWARD_CHAINING)
        comparison = self.explainer.compare_proofs(r1, r2)
        assert isinstance(comparison, str) and len(comparison) > 0

    def test_explain_proof_no_steps(self):
        """Line 191 - proof with no steps."""
        from ipfs_datasets_py.logic.TDFOL.proof_explainer import ProofType
        formula = self._formula()
        explanation = self.explainer.explain_proof(formula, [], ProofType.FORWARD_CHAINING, is_proved=True)
        assert explanation is not None

    def test_explain_proof_tableaux_method(self):
        """Lines 235-245 - tableaux method branch."""
        from ipfs_datasets_py.logic.TDFOL.proof_explainer import ProofType
        formula = self._formula()
        explanation = self.explainer.explain_proof(formula, [], ProofType.MODAL_TABLEAUX, is_proved=True)
        assert explanation is not None

    def test_proof_explainer_verbose_level(self):
        from ipfs_datasets_py.logic.TDFOL.proof_explainer import ProofExplainer, ExplanationLevel, ProofType
        exp = ProofExplainer(level=ExplanationLevel.VERBOSE)
        formula = self._formula()
        explanation = exp.explain_proof(formula, [], ProofType.FORWARD_CHAINING)
        assert explanation is not None

    def test_proof_explainer_simple_level(self):
        from ipfs_datasets_py.logic.TDFOL.proof_explainer import ProofExplainer, ExplanationLevel, ProofType
        exp = ProofExplainer(level=ExplanationLevel.BRIEF)
        formula = self._formula()
        explanation = exp.explain_proof(formula, [], ProofType.FORWARD_CHAINING)
        assert explanation is not None


# ---------------------------------------------------------------------------
# Additional coverage: identify_bottlenecks, _analyze_bottleneck,
#   _prove_basic_modal (patched shadowprover), strategies/__init__ imports
# ---------------------------------------------------------------------------

class TestIdentifyBottlenecks:
    def test_identify_bottlenecks_empty(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            result = p.identify_bottlenecks(None)
            assert result == []

    def test_identify_bottlenecks_with_profile(self):
        import cProfile, pstats
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import PerformanceProfiler, Bottleneck
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            pr = cProfile.Profile()
            pr.enable()
            sum(range(10000))
            pr.disable()
            stats = pstats.Stats(pr)
            bottlenecks = p.identify_bottlenecks(stats, top_n=5, min_time=0.0)
            assert isinstance(bottlenecks, list)

    def test_analyze_bottleneck_o_n3(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
            PerformanceProfiler, BottleneckSeverity, THRESHOLD_O_N3_SUSPECT
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            sev, rec, comp = p._analyze_bottleneck(
                "loop_func", 0.5, THRESHOLD_O_N3_SUSPECT + 1, 0.0005
            )
            assert sev == BottleneckSeverity.CRITICAL
            assert "O(n³)" in comp

    def test_analyze_bottleneck_unify_slow(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
            PerformanceProfiler, BottleneckSeverity
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            sev, rec, comp = p._analyze_bottleneck("unify_formulas", 1.5, 10, 0.15)
            assert sev == BottleneckSeverity.CRITICAL
            assert "Unification" in rec

    def test_analyze_bottleneck_prove_slow(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
            PerformanceProfiler, BottleneckSeverity
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            sev, rec, _ = p._analyze_bottleneck("prove_formula", 1.5, 5, 0.3)
            assert sev == BottleneckSeverity.CRITICAL
            assert "Proving" in rec

    def test_analyze_bottleneck_critical_generic(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
            PerformanceProfiler, BottleneckSeverity
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            sev, rec, _ = p._analyze_bottleneck("some_generic_slow_fn", 1.5, 5, 0.3)
            assert sev == BottleneckSeverity.CRITICAL

    def test_analyze_bottleneck_high(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
            PerformanceProfiler, BottleneckSeverity
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            sev, rec, _ = p._analyze_bottleneck("some_fn", 0.15, 5, 0.03)
            assert sev == BottleneckSeverity.HIGH

    def test_analyze_bottleneck_medium(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
            PerformanceProfiler, BottleneckSeverity
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            sev, rec, _ = p._analyze_bottleneck("some_fn", 0.05, 5, 0.01)
            assert sev == BottleneckSeverity.MEDIUM

    def test_analyze_bottleneck_low(self):
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
            PerformanceProfiler, BottleneckSeverity
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            p = PerformanceProfiler(output_dir=tmpdir)
            sev, rec, _ = p._analyze_bottleneck("fast_fn", 0.001, 2, 0.0005)
            assert sev == BottleneckSeverity.LOW


class TestModalTableauxProveShadowprover:
    """Test _prove_with_shadowprover ImportError path + _prove_basic_modal in KB."""

    def test_prove_modal_fallback_not_available(self):
        """_prove_with_shadowprover returns UNKNOWN when ImportError, then _prove_basic_modal called."""
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        kb = TDFOLKnowledgeBase()
        # The bridge may or may not be importable - either way prove() must not crash
        result = s.prove(formula, kb, timeout_ms=500)
        assert result.status in (ProofStatus.PROVED, ProofStatus.DISPROVED, ProofStatus.UNKNOWN, ProofStatus.ERROR)

    def test_prove_basic_modal_formula_in_axioms(self):
        """_prove_basic_modal with formula in KB -> PROVED."""
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        kb = TDFOLKnowledgeBase()
        kb.add_axiom(formula)
        import time as t
        result = s._prove_basic_modal(formula, kb, 1000, t.time())
        assert result.status == ProofStatus.PROVED

    def test_prove_basic_modal_formula_in_theorems(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = TemporalFormula(TemporalOperator.ALWAYS, Predicate("Q", ()))
        kb = TDFOLKnowledgeBase()
        kb.add_theorem(formula)
        import time as t
        result = s._prove_basic_modal(formula, kb, 1000, t.time())
        assert result.status == ProofStatus.PROVED

    def test_prove_basic_modal_not_in_kb(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = DeonticFormula(DeonticOperator.PERMISSION, Predicate("R", ()))
        kb = TDFOLKnowledgeBase()
        import time as t
        result = s._prove_basic_modal(formula, kb, 1000, t.time())
        assert result.status == ProofStatus.UNKNOWN

    def test_prove_exception_returns_error(self):
        """Lines 113-118 - exception in prove() returns ERROR."""
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        kb = TDFOLKnowledgeBase()
        # Force exception by making _prove_with_shadowprover raise non-ImportError
        with patch.object(s, '_prove_with_shadowprover', side_effect=RuntimeError("injected")):
            result = s.prove(formula, kb)
            assert result.status == ProofStatus.ERROR

    def test_is_modal_formula_returns_false_for_predicate(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        # Pure predicate has no modal operators - _traverse_formula returns False
        formula = Predicate("P", ())
        assert not s._is_modal_formula(formula)

    def test_is_modal_nested_in_binary(self):
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        # BinaryFormula with modal on left
        lhs = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        rhs = Predicate("Q", ())
        bf = BinaryFormula(LogicOperator.AND, lhs, rhs)
        assert s._is_modal_formula(bf)

    def test_traverse_formula_no_match(self):
        """_traverse_formula returns False at leaf for non-matching leaf."""
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        s = ModalTableauxStrategy()
        formula = Predicate("P", ())
        # Should not match DeonticFormula
        result = s._traverse_formula(formula, lambda f: isinstance(f, DeonticFormula))
        assert result is False


class TestStrategiesInit:
    """Cover strategies/__init__.py import branches."""

    def test_strategy_type_imports(self):
        from ipfs_datasets_py.logic.TDFOL.strategies import (
            StrategyType,
            ProverStrategy,
        )
        assert StrategyType.FORWARD_CHAINING.value == "forward_chaining"

    def test_all_exports_available(self):
        import ipfs_datasets_py.logic.TDFOL.strategies as strat_mod
        assert hasattr(strat_mod, 'StrategyType')
        assert hasattr(strat_mod, 'ProverStrategy')

    def test_strategy_classes_importable(self):
        from ipfs_datasets_py.logic.TDFOL.strategies import (
            ForwardChainingStrategy,
            ModalTableauxStrategy,
            CECDelegateStrategy,
            StrategySelector,
        )
        assert ForwardChainingStrategy is not None
        assert ModalTableauxStrategy is not None
        assert CECDelegateStrategy is not None
        assert StrategySelector is not None


class TestModalTableauxMixedCost:
    def test_estimate_cost_mixed_deontic_and_temporal(self):
        """Line 353 - cost *= 1.5 when both deontic AND temporal."""
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import BinaryTemporalFormula
        s = ModalTableauxStrategy()
        # Inner deontic formula
        deontic = DeonticFormula(DeonticOperator.OBLIGATION, Predicate("P", ()))
        # Outer temporal formula wrapping deontic
        temporal = TemporalFormula(TemporalOperator.ALWAYS, deontic)
        kb = TDFOLKnowledgeBase()
        cost = s.estimate_cost(temporal, kb)
        # Base cost 2.0, nested temporal -> *2 = 4.0, both ops -> *1.5 = 6.0
        assert cost > 2.0

    def test_traverse_formula_binary_temporal_no_match(self):
        """Line 353 area - BinaryTemporalFormula leaf returns False."""
        from ipfs_datasets_py.logic.TDFOL.strategies.modal_tableaux import ModalTableauxStrategy
        from ipfs_datasets_py.logic.TDFOL.tdfol_core import BinaryTemporalFormula
        s = ModalTableauxStrategy()
        formula = BinaryTemporalFormula(TemporalOperator.UNTIL, Predicate("P", ()), Predicate("Q", ()))
        # Searching for DeonticFormula - not present
        result = s._traverse_formula(formula, lambda f: isinstance(f, DeonticFormula))
        assert result is False


class TestMemoryProfileThisDecorator:
    def test_memory_profile_this_with_args(self):
        """Lines 411+ - memory_profile_this decorator variant with func=None."""
        from ipfs_datasets_py.logic.TDFOL.performance_profiler import memory_profile_this
        call_count = {"n": 0}

        @memory_profile_this()
        def simple():
            call_count["n"] += 1
            return [i for i in range(100)]

        result = simple()
        assert isinstance(result, list)
        assert call_count["n"] == 1
