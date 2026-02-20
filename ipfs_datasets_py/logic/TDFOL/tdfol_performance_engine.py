"""
TDFOL Performance Engine

Business logic for TDFOL performance metrics, profiling, and dashboard generation.
"""
from __future__ import annotations

import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from ipfs_datasets_py.logic.TDFOL.performance_metrics import (
        MetricsCollector,
        get_global_collector,
        StatisticalSummary
    )
    from ipfs_datasets_py.logic.TDFOL.performance_profiler import (
        PerformanceProfiler,
        ProfilingStats,
        Bottleneck,
        ReportFormat
    )
    from ipfs_datasets_py.logic.TDFOL.performance_dashboard import (
        PerformanceDashboard,
        ProofMetrics
    )
    from ipfs_datasets_py.logic.TDFOL.tdfol_prover import TDFOLProver
    from ipfs_datasets_py.logic.TDFOL.tdfol_parser import TDFOLParser
    TDFOL_AVAILABLE = True
    IMPORT_ERROR = ""
except ImportError as e:
    TDFOL_AVAILABLE = False
    IMPORT_ERROR = str(e)

logger = logging.getLogger(__name__)


class TDFOLPerformanceEngine:
    """Engine encapsulating TDFOL performance metrics, profiling, and dashboard logic."""

    def __init__(self) -> None:
        self._dashboard: Optional[Any] = None
        self._profiler: Optional[Any] = None
        self._collector: Optional[Any] = None

    # ------------------------------------------------------------------
    # Singleton accessors
    # ------------------------------------------------------------------

    def _get_dashboard(self) -> Any:
        if self._dashboard is None:
            self._dashboard = PerformanceDashboard()
        return self._dashboard

    def _get_profiler(self) -> Any:
        if self._profiler is None:
            self._profiler = PerformanceProfiler(output_dir="/tmp/tdfol_profiling")
        return self._profiler

    def _get_collector(self) -> Any:
        if self._collector is None:
            self._collector = get_global_collector()
        return self._collector

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_metrics(self) -> Dict[str, Any]:
        """Get current TDFOL performance metrics."""
        if not TDFOL_AVAILABLE:
            return {"error": "TDFOL not available", "details": IMPORT_ERROR,
                    "suggestion": "Install TDFOL dependencies"}
        try:
            dashboard = self._get_dashboard()
            collector = self._get_collector()
            stats = dashboard.get_statistics()
            collector_stats = collector.get_statistics()
            return {
                "dashboard_stats": stats,
                "collector_stats": collector_stats,
                "collector_summary": {
                    "timing_operations": len(collector_stats.get("timing", {})),
                    "memory_operations": len(collector_stats.get("memory", {})),
                    "counters": len(collector_stats.get("counters", {})),
                    "gauges": len(collector_stats.get("gauges", {})),
                    "histograms": len(collector_stats.get("histograms", {})),
                },
                "metadata": {
                    "dashboard_proofs_recorded": len(dashboard.proof_metrics),
                    "dashboard_uptime_seconds": dashboard.get_uptime(),
                    "collector_uptime_seconds": collector.get_uptime(),
                },
            }
        except Exception as e:
            logger.error(f"Failed to get TDFOL metrics: {e}", exc_info=True)
            return {"error": "Failed to retrieve metrics", "details": str(e),
                    "suggestion": "Check TDFOL dashboard initialization"}

    def profile_operation(
        self,
        formula_str: str,
        kb_formulas: Optional[List[str]] = None,
        runs: int = 10,
        strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Profile a TDFOL proving operation."""
        if not TDFOL_AVAILABLE:
            return {"error": "TDFOL not available", "details": IMPORT_ERROR}
        try:
            profiler = self._get_profiler()
            parser = TDFOLParser()
            formula = parser.parse(formula_str)
            kb = None
            if kb_formulas:
                from ipfs_datasets_py.logic.TDFOL.tdfol_optimization import KnowledgeBase
                kb = KnowledgeBase()
                for kb_formula_str in kb_formulas:
                    kb.add(parser.parse(kb_formula_str))
            prover = TDFOLProver(kb=kb, cache_size=1000)
            stats = profiler.profile_prover(prover, formula, runs=runs)
            bottlenecks = []
            if stats.profile_data:
                bottleneck_objs = profiler.identify_bottlenecks(stats.profile_data, top_n=10)
                bottlenecks = [b.to_dict() for b in bottleneck_objs]
            return {
                "formula": formula_str,
                "runs": runs,
                "strategy": strategy or "auto",
                "kb_size": len(kb_formulas) if kb_formulas else 0,
                "timing": {
                    "mean_time_ms": stats.mean_time_ms,
                    "median_time_ms": stats.median_time * 1000,
                    "min_time_ms": stats.min_time * 1000,
                    "max_time_ms": stats.max_time * 1000,
                    "std_dev_ms": stats.std_dev * 1000,
                    "total_time_s": stats.total_time,
                },
                "performance": {
                    "calls_per_run": stats.calls_per_run,
                    "meets_threshold": stats.meets_threshold,
                    "bottlenecks": bottlenecks,
                },
                "metadata": {"function": stats.function_name},
            }
        except Exception as e:
            logger.error(f"Failed to profile operation: {e}", exc_info=True)
            return {"error": "Profiling failed", "details": str(e),
                    "suggestion": "Check formula syntax and KB formulas"}

    def generate_dashboard(
        self,
        output_path: Optional[str] = None,
        include_profiling: bool = False,
    ) -> Dict[str, Any]:
        """Generate TDFOL performance dashboard HTML."""
        if not TDFOL_AVAILABLE:
            return {"error": "TDFOL not available", "details": IMPORT_ERROR}
        try:
            dashboard = self._get_dashboard()
            if output_path is None:
                temp_file = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".html", delete=False, prefix="tdfol_dashboard_"
                )
                output_path = temp_file.name
                temp_file.close()
            dashboard.generate_html(output_path)
            stats = dashboard.get_statistics()
            result: Dict[str, Any] = {
                "success": True,
                "file_path": output_path,
                "metrics_count": len(dashboard.proof_metrics),
                "summary": {
                    "total_proofs": stats.get("total_proofs", 0),
                    "success_rate": stats.get("success_rate", 0.0),
                    "avg_time_ms": stats.get("avg_proof_time_ms", 0.0),
                    "cache_hit_rate": stats.get("cache_hit_rate", 0.0),
                },
            }
            if include_profiling:
                profiler = self._get_profiler()
                result["profiling_history"] = profiler.history[-10:]
            return result
        except Exception as e:
            logger.error(f"Failed to generate dashboard: {e}", exc_info=True)
            return {"error": "Dashboard generation failed", "details": str(e),
                    "suggestion": "Check permissions and disk space"}

    def export_statistics(
        self,
        fmt: str = "json",
        include_raw_data: bool = False,
    ) -> Dict[str, Any]:
        """Export TDFOL performance statistics."""
        if not TDFOL_AVAILABLE:
            return {"error": "TDFOL not available", "details": IMPORT_ERROR}
        try:
            dashboard = self._get_dashboard()
            collector = self._get_collector()
            stats = dashboard.get_statistics()
            collector_export = collector.export_dict()
            export_data: Dict[str, Any] = {
                "timestamp": dashboard.start_time,
                "uptime_seconds": dashboard.get_uptime(),
                "dashboard_stats": stats,
                "collector_stats": collector_export,
                "format": fmt,
            }
            if include_raw_data:
                export_data["raw_proof_metrics"] = [
                    m.to_dict() for m in dashboard.proof_metrics[-100:]
                ]
            if fmt == "json":
                export_data["json_string"] = json.dumps(export_data, indent=2)
            elif fmt == "prometheus":
                export_data["prometheus_metrics"] = self._convert_to_prometheus(
                    stats, collector_export
                )
            return export_data
        except Exception as e:
            logger.error(f"Failed to export statistics: {e}", exc_info=True)
            return {"error": "Export failed", "details": str(e)}

    def get_profiler_report(
        self,
        report_format: str = "text",
        top_n: int = 20,
    ) -> Dict[str, Any]:
        """Get detailed TDFOL profiler report."""
        if not TDFOL_AVAILABLE:
            return {"error": "TDFOL not available", "details": IMPORT_ERROR}
        try:
            profiler = self._get_profiler()
            if not profiler.history:
                return {"warning": "No profiling data available",
                        "suggestion": "Run profile_operation first"}
            latest = profiler.history[-1]
            report: Dict[str, Any] = {
                "format": report_format,
                "latest_run": latest,
                "history_count": len(profiler.history),
                "baseline": profiler.baseline if profiler.baseline else None,
            }
            if report_format == "html":
                profiler.generate_report(format=ReportFormat.HTML)
                report["html_path"] = str(
                    profiler.output_dir / "profiling_report.html"
                )
            return report
        except Exception as e:
            logger.error(f"Failed to get profiler report: {e}", exc_info=True)
            return {"error": "Report generation failed", "details": str(e)}

    def compare_strategies(
        self,
        formula_str: str,
        strategies: Optional[List[str]] = None,
        kb_formulas: Optional[List[str]] = None,
        runs_per_strategy: int = 10,
    ) -> Dict[str, Any]:
        """Compare TDFOL proving strategies performance."""
        if not TDFOL_AVAILABLE:
            return {"error": "TDFOL not available", "details": IMPORT_ERROR}
        if strategies is None:
            strategies = ["forward", "modal", "cec"]
        try:
            results: Dict[str, Any] = {}
            for strategy in strategies:
                result = self.profile_operation(
                    formula_str=formula_str,
                    kb_formulas=kb_formulas,
                    runs=runs_per_strategy,
                    strategy=strategy,
                )
                if "error" not in result:
                    results[strategy] = result["timing"]
            if not results:
                return {"error": "No strategies successfully profiled",
                        "suggestion": "Check formula syntax and strategy names"}
            best_strategy = min(results.items(), key=lambda x: x[1]["mean_time_ms"])
            worst_strategy = max(results.items(), key=lambda x: x[1]["mean_time_ms"])
            speedup = worst_strategy[1]["mean_time_ms"] / best_strategy[1]["mean_time_ms"]
            return {
                "formula": formula_str,
                "strategies_compared": len(results),
                "runs_per_strategy": runs_per_strategy,
                "results": results,
                "best_strategy": {"name": best_strategy[0], **best_strategy[1]},
                "worst_strategy": {"name": worst_strategy[0], **worst_strategy[1]},
                "speedup": speedup,
                "recommendation": (
                    f"Use '{best_strategy[0]}' strategy "
                    f"({speedup:.1f}x faster than '{worst_strategy[0]}')"
                ),
            }
        except Exception as e:
            logger.error(f"Failed to compare strategies: {e}", exc_info=True)
            return {"error": "Strategy comparison failed", "details": str(e)}

    def check_regression(
        self,
        baseline_path: Optional[str] = None,
        threshold_percent: float = 10.0,
    ) -> Dict[str, Any]:
        """Check for TDFOL performance regressions."""
        if not TDFOL_AVAILABLE:
            return {"error": "TDFOL not available", "details": IMPORT_ERROR}
        try:
            profiler = self._get_profiler()
            baseline: Dict[str, Any] = {}
            if baseline_path and Path(baseline_path).exists():
                with open(baseline_path, "r") as f:
                    baseline = json.load(f)
            elif profiler.baseline:
                baseline = profiler.baseline
            else:
                return {"warning": "No baseline available",
                        "suggestion": "Provide baseline_path or run profiler with baseline"}
            collector = self._get_collector()
            current_stats = collector.get_statistics()
            regressions = []
            for metric_name, baseline_value in baseline.items():
                if metric_name in current_stats.get("timing", {}):
                    current_value = current_stats["timing"][metric_name].get("mean", 0)
                    if current_value > baseline_value * (1 + threshold_percent / 100):
                        regression_percent = (
                            (current_value - baseline_value) / baseline_value * 100
                        )
                        regressions.append({
                            "metric": metric_name,
                            "baseline": baseline_value,
                            "current": current_value,
                            "regression_percent": regression_percent,
                            "threshold_percent": threshold_percent,
                            "severity": "critical" if regression_percent > 20 else "warning",
                        })
            result: Dict[str, Any] = {
                "regressions_found": len(regressions) > 0,
                "regression_count": len(regressions),
                "threshold_percent": threshold_percent,
                "regressions": regressions,
                "baseline_metrics": len(baseline),
                "current_metrics": len(current_stats.get("timing", {})),
            }
            if regressions:
                result["recommendation"] = (
                    f"Investigate {len(regressions)} performance regressions"
                )
            else:
                result["status"] = "All metrics within baseline threshold"
            return result
        except Exception as e:
            logger.error(f"Failed to check regressions: {e}", exc_info=True)
            return {"error": "Regression check failed", "details": str(e)}

    def reset_metrics(self) -> Dict[str, Any]:
        """Reset TDFOL performance metrics and collectors."""
        if not TDFOL_AVAILABLE:
            return {"error": "TDFOL not available", "details": IMPORT_ERROR}
        try:
            metrics_count = 0
            if self._dashboard:
                metrics_count = len(self._dashboard.proof_metrics)
            self._dashboard = PerformanceDashboard()
            from ipfs_datasets_py.logic.TDFOL.performance_metrics import reset_global_collector
            reset_global_collector()
            self._collector = get_global_collector()
            return {
                "success": True,
                "metrics_cleared": metrics_count,
                "timestamp": time.time(),
                "message": "TDFOL metrics reset successfully",
            }
        except Exception as e:
            logger.error(f"Failed to reset metrics: {e}", exc_info=True)
            return {"error": "Reset failed", "details": str(e)}

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _convert_to_prometheus(
        self,
        dashboard_stats: Dict[str, Any],
        collector_stats: Dict[str, Any],
    ) -> str:
        """Convert metrics to Prometheus format."""
        lines = []
        if "total_proofs" in dashboard_stats:
            lines.append(f"tdfol_total_proofs {dashboard_stats['total_proofs']}")
        if "success_rate" in dashboard_stats:
            lines.append(f"tdfol_success_rate {dashboard_stats['success_rate']}")
        if "avg_proof_time_ms" in dashboard_stats:
            lines.append(f"tdfol_avg_proof_time_ms {dashboard_stats['avg_proof_time_ms']}")
        if "cache_hit_rate" in dashboard_stats:
            lines.append(f"tdfol_cache_hit_rate {dashboard_stats['cache_hit_rate']}")
        timing_stats = collector_stats.get("timing", {})
        for operation_name, stats in timing_stats.items():
            if isinstance(stats, dict) and "mean" in stats:
                safe_name = operation_name.replace(".", "_").replace("-", "_")
                lines.append(
                    f'tdfol_operation_mean_ms{{operation="{safe_name}"}} {stats["mean"]}'
                )
                if "p95" in stats:
                    lines.append(
                        f'tdfol_operation_p95_ms{{operation="{safe_name}"}} {stats["p95"]}'
                    )
                if "p99" in stats:
                    lines.append(
                        f'tdfol_operation_p99_ms{{operation="{safe_name}"}} {stats["p99"]}'
                    )
        counters = collector_stats.get("counters", {})
        for counter_name, value in counters.items():
            safe_name = counter_name.replace(".", "_").replace("-", "_")
            lines.append(f'tdfol_counter{{name="{safe_name}"}} {value}')
        memory_stats = collector_stats.get("memory", {})
        for operation_name, stats in memory_stats.items():
            if isinstance(stats, dict) and "mean" in stats:
                safe_name = operation_name.replace(".", "_").replace("-", "_")
                lines.append(
                    f'tdfol_memory_mean_mb{{operation="{safe_name}"}} {stats["mean"]}'
                )
        return "\n".join(lines)
