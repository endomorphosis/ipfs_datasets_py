"""
TDFOL Performance Dashboard Tool for MCP Server

This MCP tool provides access to TDFOL performance metrics, profiling data,
and performance dashboards through the Model Context Protocol.

Features:
1. Real-time metrics retrieval from TDFOL operations
2. Performance profiling and benchmarking
3. HTML dashboard generation
4. Integration with MCP monitoring system
5. Statistics export (JSON format)

MCP Tools Provided:
- get_tdfol_metrics: Get current performance metrics
- profile_tdfol_operation: Profile a specific TDFOL operation
- generate_tdfol_dashboard: Generate HTML performance dashboard
- export_tdfol_statistics: Export metrics as JSON
- get_tdfol_profiler_report: Get detailed profiling report
- compare_tdfol_strategies: Compare performance across strategies
- check_tdfol_performance_regression: Check for performance regressions

Author: TDFOL Team
Date: 2026-02-19
Phase: 1 (Code Consolidation)
Task: 1.4 (MCP Dashboard Integration)
"""

from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

# Import TDFOL performance infrastructure
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
except ImportError as e:
    TDFOL_AVAILABLE = False
    IMPORT_ERROR = str(e)

logger = logging.getLogger(__name__)

# Global instances for persistence across MCP calls
_dashboard: Optional[PerformanceDashboard] = None
_profiler: Optional[PerformanceProfiler] = None
_collector: Optional[MetricsCollector] = None


def _get_dashboard() -> PerformanceDashboard:
    """Get or create global dashboard instance."""
    global _dashboard
    if _dashboard is None:
        _dashboard = PerformanceDashboard()
    return _dashboard


def _get_profiler() -> PerformanceProfiler:
    """Get or create global profiler instance."""
    global _profiler
    if _profiler is None:
        _profiler = PerformanceProfiler(output_dir="/tmp/tdfol_profiling")
    return _profiler


def _get_collector() -> MetricsCollector:
    """Get global metrics collector instance."""
    global _collector
    if _collector is None:
        _collector = get_global_collector()
    return _collector


# ============================================================================
# MCP Tool Functions
# ============================================================================


def get_tdfol_metrics() -> Dict[str, Any]:
    """
    Get current TDFOL performance metrics.
    
    Returns real-time metrics from TDFOL operations including:
    - Proof attempt counts and success rates
    - Average proof times (P50, P95, P99)
    - Cache hit rates
    - Strategy usage statistics
    - Memory usage metrics
    - Formula complexity distribution
    
    Returns:
        Dictionary with comprehensive metrics data
        
    Example:
        >>> metrics = get_tdfol_metrics()
        >>> print(f"Cache hit rate: {metrics['cache_hit_rate']:.1%}")
        >>> print(f"P95 proof time: {metrics['timing_stats']['p95']:.2f}ms")
    """
    if not TDFOL_AVAILABLE:
        return {
            'error': 'TDFOL not available',
            'details': IMPORT_ERROR,
            'suggestion': 'Install TDFOL dependencies'
        }
    
    try:
        dashboard = _get_dashboard()
        collector = _get_collector()
        
        # Get dashboard statistics
        stats = dashboard.get_statistics()
        
        # Get metrics collector statistics
        collector_stats = collector.get_statistics()
        
        # Combine metrics
        combined_metrics = {
            'dashboard_stats': stats,
            'collector_stats': collector_stats,
            'collector_summary': {
                'timing_operations': len(collector_stats.get('timing', {})),
                'memory_operations': len(collector_stats.get('memory', {})),
                'counters': len(collector_stats.get('counters', {})),
                'gauges': len(collector_stats.get('gauges', {})),
                'histograms': len(collector_stats.get('histograms', {}))
            },
            'metadata': {
                'dashboard_proofs_recorded': len(dashboard.proof_metrics),
                'dashboard_uptime_seconds': dashboard.get_uptime(),
                'collector_uptime_seconds': collector.get_uptime()
            }
        }
        
        return combined_metrics
        
    except Exception as e:
        logger.error(f"Failed to get TDFOL metrics: {e}", exc_info=True)
        return {
            'error': 'Failed to retrieve metrics',
            'details': str(e),
            'suggestion': 'Check TDFOL dashboard initialization'
        }


def profile_tdfol_operation(
    formula_str: str,
    kb_formulas: Optional[List[str]] = None,
    runs: int = 10,
    strategy: Optional[str] = None
) -> Dict[str, Any]:
    """
    Profile a TDFOL proving operation.
    
    Runs a TDFOL proof multiple times and collects detailed performance metrics
    including timing, memory usage, bottlenecks, and call counts.
    
    Args:
        formula_str: Formula to prove (TDFOL syntax)
        kb_formulas: Optional knowledge base formulas
        runs: Number of profiling runs (default: 10)
        strategy: Optional strategy to use ('forward', 'modal', 'cec')
    
    Returns:
        Dictionary with profiling results including:
        - mean_time_ms: Average proof time
        - std_dev_ms: Standard deviation
        - min/max times
        - bottlenecks: List of performance bottlenecks
        - memory_stats: Memory usage information
        
    Example:
        >>> result = profile_tdfol_operation(
        ...     "P(x) → Q(x)",
        ...     kb_formulas=["P(a)", "∀x(Q(x) → R(x))"],
        ...     runs=20
        ... )
        >>> print(f"Mean time: {result['mean_time_ms']:.2f}ms")
    """
    if not TDFOL_AVAILABLE:
        return {
            'error': 'TDFOL not available',
            'details': IMPORT_ERROR
        }
    
    try:
        profiler = _get_profiler()
        parser = TDFOLParser()
        
        # Parse formula
        formula = parser.parse(formula_str)
        
        # Create KB if provided
        kb = None
        if kb_formulas:
            from ipfs_datasets_py.logic.TDFOL.tdfol_optimization import KnowledgeBase
            kb = KnowledgeBase()
            for kb_formula_str in kb_formulas:
                kb_formula = parser.parse(kb_formula_str)
                kb.add(kb_formula)
        
        # Create prover
        prover = TDFOLProver(kb=kb, cache_size=1000)
        
        # Profile the operation
        stats = profiler.profile_prover(
            prover,
            formula,
            runs=runs
        )
        
        # Identify bottlenecks
        bottlenecks = []
        if stats.profile_data:
            bottleneck_objs = profiler.identify_bottlenecks(
                stats.profile_data,
                top_n=10
            )
            bottlenecks = [b.to_dict() for b in bottleneck_objs]
        
        # Compile results
        results = {
            'formula': formula_str,
            'runs': runs,
            'strategy': strategy or 'auto',
            'kb_size': len(kb_formulas) if kb_formulas else 0,
            'timing': {
                'mean_time_ms': stats.mean_time_ms,
                'median_time_ms': stats.median_time * 1000,
                'min_time_ms': stats.min_time * 1000,
                'max_time_ms': stats.max_time * 1000,
                'std_dev_ms': stats.std_dev * 1000,
                'total_time_s': stats.total_time
            },
            'performance': {
                'calls_per_run': stats.calls_per_run,
                'meets_threshold': stats.meets_threshold,
                'bottlenecks': bottlenecks
            },
            'metadata': {
                'function': stats.function_name
            }
        }
        
        return results
        
    except Exception as e:
        logger.error(f"Failed to profile operation: {e}", exc_info=True)
        return {
            'error': 'Profiling failed',
            'details': str(e),
            'suggestion': 'Check formula syntax and KB formulas'
        }


def generate_tdfol_dashboard(
    output_path: Optional[str] = None,
    include_profiling: bool = False
) -> Dict[str, Any]:
    """
    Generate TDFOL performance dashboard HTML.
    
    Creates an interactive HTML dashboard with real-time performance metrics,
    charts, and visualizations using Chart.js.
    
    Args:
        output_path: Path to save HTML file (default: temp file)
        include_profiling: Include detailed profiling data
    
    Returns:
        Dictionary with:
        - file_path: Path to generated HTML
        - metrics_count: Number of metrics in dashboard
        - success: Whether generation succeeded
        
    Example:
        >>> result = generate_tdfol_dashboard(
        ...     output_path="/tmp/tdfol_dashboard.html",
        ...     include_profiling=True
        ... )
        >>> print(f"Dashboard: {result['file_path']}")
    """
    if not TDFOL_AVAILABLE:
        return {
            'error': 'TDFOL not available',
            'details': IMPORT_ERROR
        }
    
    try:
        dashboard = _get_dashboard()
        
        # Determine output path
        if output_path is None:
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.html',
                delete=False,
                prefix='tdfol_dashboard_'
            )
            output_path = temp_file.name
            temp_file.close()
        
        # Generate HTML
        dashboard.generate_html(output_path)
        
        # Get statistics for response
        stats = dashboard.get_statistics()
        
        result = {
            'success': True,
            'file_path': output_path,
            'metrics_count': len(dashboard.proof_metrics),
            'summary': {
                'total_proofs': stats.get('total_proofs', 0),
                'success_rate': stats.get('success_rate', 0.0),
                'avg_time_ms': stats.get('avg_proof_time_ms', 0.0),
                'cache_hit_rate': stats.get('cache_hit_rate', 0.0)
            }
        }
        
        if include_profiling:
            profiler = _get_profiler()
            result['profiling_history'] = profiler.history[-10:]  # Last 10 runs
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to generate dashboard: {e}", exc_info=True)
        return {
            'error': 'Dashboard generation failed',
            'details': str(e),
            'suggestion': 'Check permissions and disk space'
        }


def export_tdfol_statistics(
    format: str = "json",
    include_raw_data: bool = False
) -> Dict[str, Any]:
    """
    Export TDFOL performance statistics.
    
    Exports aggregated statistics from the TDFOL performance dashboard
    in various formats for integration with monitoring systems.
    
    Args:
        format: Export format ('json', 'dict', 'prometheus')
        include_raw_data: Include raw proof metrics (can be large)
    
    Returns:
        Dictionary with exported statistics
        
    Example:
        >>> stats = export_tdfol_statistics(format="json")
        >>> print(json.dumps(stats, indent=2))
    """
    if not TDFOL_AVAILABLE:
        return {
            'error': 'TDFOL not available',
            'details': IMPORT_ERROR
        }
    
    try:
        dashboard = _get_dashboard()
        collector = _get_collector()
        
        # Get aggregated statistics
        stats = dashboard.get_statistics()
        collector_export = collector.export_dict()
        
        export_data = {
            'timestamp': dashboard.start_time,
            'uptime_seconds': dashboard.get_uptime(),
            'dashboard_stats': stats,
            'collector_stats': collector_export,
            'format': format
        }
        
        if include_raw_data:
            export_data['raw_proof_metrics'] = [
                m.to_dict() for m in dashboard.proof_metrics[-100:]  # Last 100
            ]
        
        if format == "json":
            export_data['json_string'] = json.dumps(export_data, indent=2)
        elif format == "prometheus":
            # Convert to Prometheus format
            prom_metrics = _convert_to_prometheus(stats, collector_export)
            export_data['prometheus_metrics'] = prom_metrics
        
        return export_data
        
    except Exception as e:
        logger.error(f"Failed to export statistics: {e}", exc_info=True)
        return {
            'error': 'Export failed',
            'details': str(e)
        }


def get_tdfol_profiler_report(
    report_format: str = "text",
    top_n: int = 20
) -> Dict[str, Any]:
    """
    Get detailed TDFOL profiler report.
    
    Retrieves the most recent profiling data including bottlenecks,
    hot paths, and performance recommendations.
    
    Args:
        report_format: Report format ('text', 'json', 'html')
        top_n: Number of top bottlenecks to include
    
    Returns:
        Dictionary with profiling report data
        
    Example:
        >>> report = get_tdfol_profiler_report(report_format="json", top_n=10)
        >>> for bottleneck in report['bottlenecks']:
        ...     print(f"{bottleneck['function']}: {bottleneck['recommendation']}")
    """
    if not TDFOL_AVAILABLE:
        return {
            'error': 'TDFOL not available',
            'details': IMPORT_ERROR
        }
    
    try:
        profiler = _get_profiler()
        
        # Get latest profiling history
        if not profiler.history:
            return {
                'warning': 'No profiling data available',
                'suggestion': 'Run profile_tdfol_operation first'
            }
        
        latest = profiler.history[-1]
        
        report = {
            'format': report_format,
            'latest_run': latest,
            'history_count': len(profiler.history),
            'baseline': profiler.baseline if profiler.baseline else None
        }
        
        # Generate formatted report if HTML
        if report_format == "html":
            temp_file = tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.html',
                delete=False,
                prefix='tdfol_profiler_'
            )
            profiler.generate_report(
                format=ReportFormat.HTML
            )
            report['html_path'] = str(profiler.output_dir / "profiling_report.html")
        
        return report
        
    except Exception as e:
        logger.error(f"Failed to get profiler report: {e}", exc_info=True)
        return {
            'error': 'Report generation failed',
            'details': str(e)
        }


def compare_tdfol_strategies(
    formula_str: str,
    strategies: Optional[List[str]] = None,
    kb_formulas: Optional[List[str]] = None,
    runs_per_strategy: int = 10
) -> Dict[str, Any]:
    """
    Compare TDFOL proving strategies performance.
    
    Profiles multiple strategies on the same formula to compare their
    relative performance and identify the best strategy for specific cases.
    
    Args:
        formula_str: Formula to prove
        strategies: List of strategies to compare (default: all available)
        kb_formulas: Optional KB formulas
        runs_per_strategy: Profiling runs per strategy
    
    Returns:
        Dictionary with comparison results and recommendations
        
    Example:
        >>> comparison = compare_tdfol_strategies(
        ...     "□P(x) → ◊Q(x)",
        ...     strategies=['forward', 'modal', 'cec']
        ... )
        >>> best = comparison['best_strategy']
        >>> print(f"Best: {best['name']} ({best['mean_time_ms']:.2f}ms)")
    """
    if not TDFOL_AVAILABLE:
        return {
            'error': 'TDFOL not available',
            'details': IMPORT_ERROR
        }
    
    if strategies is None:
        strategies = ['forward', 'modal', 'cec']
    
    try:
        results = {}
        
        for strategy in strategies:
            # Profile this strategy
            result = profile_tdfol_operation(
                formula_str=formula_str,
                kb_formulas=kb_formulas,
                runs=runs_per_strategy,
                strategy=strategy
            )
            
            if 'error' not in result:
                results[strategy] = result['timing']
        
        if not results:
            return {
                'error': 'No strategies successfully profiled',
                'suggestion': 'Check formula syntax and strategy names'
            }
        
        # Find best strategy
        best_strategy = min(results.items(), key=lambda x: x[1]['mean_time_ms'])
        worst_strategy = max(results.items(), key=lambda x: x[1]['mean_time_ms'])
        
        speedup = worst_strategy[1]['mean_time_ms'] / best_strategy[1]['mean_time_ms']
        
        comparison = {
            'formula': formula_str,
            'strategies_compared': len(results),
            'runs_per_strategy': runs_per_strategy,
            'results': results,
            'best_strategy': {
                'name': best_strategy[0],
                **best_strategy[1]
            },
            'worst_strategy': {
                'name': worst_strategy[0],
                **worst_strategy[1]
            },
            'speedup': speedup,
            'recommendation': f"Use '{best_strategy[0]}' strategy ({speedup:.1f}x faster than '{worst_strategy[0]}')"
        }
        
        return comparison
        
    except Exception as e:
        logger.error(f"Failed to compare strategies: {e}", exc_info=True)
        return {
            'error': 'Strategy comparison failed',
            'details': str(e)
        }


def check_tdfol_performance_regression(
    baseline_path: Optional[str] = None,
    threshold_percent: float = 10.0
) -> Dict[str, Any]:
    """
    Check for TDFOL performance regressions.
    
    Compares current performance metrics against a baseline to detect
    performance regressions that exceed the specified threshold.
    
    Args:
        baseline_path: Path to baseline performance data JSON
        threshold_percent: Regression threshold (default: 10%)
    
    Returns:
        Dictionary with regression analysis results
        
    Example:
        >>> result = check_tdfol_performance_regression(
        ...     baseline_path="/path/to/baseline.json",
        ...     threshold_percent=5.0
        ... )
        >>> if result['regressions_found']:
        ...     print(f"Warning: {result['regression_count']} regressions detected!")
    """
    if not TDFOL_AVAILABLE:
        return {
            'error': 'TDFOL not available',
            'details': IMPORT_ERROR
        }
    
    try:
        profiler = _get_profiler()
        
        # Load baseline if provided
        baseline = {}
        if baseline_path and Path(baseline_path).exists():
            with open(baseline_path, 'r') as f:
                baseline = json.load(f)
        elif profiler.baseline:
            baseline = profiler.baseline
        else:
            return {
                'warning': 'No baseline available',
                'suggestion': 'Provide baseline_path or run profiler with baseline'
            }
        
        # Get current metrics
        collector = _get_collector()
        current_stats = collector.get_statistics()
        
        # Detect regressions
        regressions = []
        for metric_name, baseline_value in baseline.items():
            if metric_name in current_stats.get('timing', {}):
                current_value = current_stats['timing'][metric_name].get('mean', 0)
                if current_value > baseline_value * (1 + threshold_percent / 100):
                    regression_percent = ((current_value - baseline_value) / baseline_value) * 100
                    regressions.append({
                        'metric': metric_name,
                        'baseline': baseline_value,
                        'current': current_value,
                        'regression_percent': regression_percent,
                        'threshold_percent': threshold_percent,
                        'severity': 'critical' if regression_percent > 20 else 'warning'
                    })
        
        result = {
            'regressions_found': len(regressions) > 0,
            'regression_count': len(regressions),
            'threshold_percent': threshold_percent,
            'regressions': regressions,
            'baseline_metrics': len(baseline),
            'current_metrics': len(current_stats.get('timing', {}))
        }
        
        if regressions:
            result['recommendation'] = f"Investigate {len(regressions)} performance regressions"
        else:
            result['status'] = 'All metrics within baseline threshold'
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to check regressions: {e}", exc_info=True)
        return {
            'error': 'Regression check failed',
            'details': str(e)
        }


def reset_tdfol_metrics() -> Dict[str, Any]:
    """
    Reset TDFOL performance metrics and collectors.
    
    Clears all recorded metrics from the dashboard and resets
    the metrics collector. Useful for starting fresh benchmarking sessions.
    
    Returns:
        Dictionary with reset confirmation
        
    Example:
        >>> result = reset_tdfol_metrics()
        >>> print(f"Reset {result['metrics_cleared']} metrics")
    """
    if not TDFOL_AVAILABLE:
        return {
            'error': 'TDFOL not available',
            'details': IMPORT_ERROR
        }
    
    try:
        global _dashboard, _collector
        
        # Count metrics before reset
        metrics_count = 0
        if _dashboard:
            metrics_count = len(_dashboard.proof_metrics)
        
        # Reset dashboard
        _dashboard = PerformanceDashboard()
        
        # Reset collector
        from ipfs_datasets_py.logic.TDFOL.performance_metrics import reset_global_collector
        reset_global_collector()
        _collector = get_global_collector()
        
        return {
            'success': True,
            'metrics_cleared': metrics_count,
            'timestamp': time.time(),
            'message': 'TDFOL metrics reset successfully'
        }
        
    except Exception as e:
        logger.error(f"Failed to reset metrics: {e}", exc_info=True)
        return {
            'error': 'Reset failed',
            'details': str(e)
        }


def _convert_to_prometheus(
    dashboard_stats: Dict[str, Any],
    collector_stats: Dict[str, Any]
) -> str:
    """
    Convert metrics to Prometheus format.
    
    Args:
        dashboard_stats: Statistics from dashboard
        collector_stats: Statistics from metrics collector
    
    Returns:
        Prometheus-formatted metrics string
    """
    lines = []
    
    # Dashboard metrics
    if 'total_proofs' in dashboard_stats:
        lines.append(f"tdfol_total_proofs {dashboard_stats['total_proofs']}")
    if 'success_rate' in dashboard_stats:
        lines.append(f"tdfol_success_rate {dashboard_stats['success_rate']}")
    if 'avg_proof_time_ms' in dashboard_stats:
        lines.append(f"tdfol_avg_proof_time_ms {dashboard_stats['avg_proof_time_ms']}")
    if 'cache_hit_rate' in dashboard_stats:
        lines.append(f"tdfol_cache_hit_rate {dashboard_stats['cache_hit_rate']}")
    
    # Collector metrics
    timing_stats = collector_stats.get('timing', {})
    for operation_name, stats in timing_stats.items():
        if isinstance(stats, dict) and 'mean' in stats:
            safe_name = operation_name.replace('.', '_').replace('-', '_')
            lines.append(f"tdfol_operation_mean_ms{{operation=\"{safe_name}\"}} {stats['mean']}")
            if 'p95' in stats:
                lines.append(f"tdfol_operation_p95_ms{{operation=\"{safe_name}\"}} {stats['p95']}")
            if 'p99' in stats:
                lines.append(f"tdfol_operation_p99_ms{{operation=\"{safe_name}\"}} {stats['p99']}")
    
    # Counters
    counters = collector_stats.get('counters', {})
    for counter_name, value in counters.items():
        safe_name = counter_name.replace('.', '_').replace('-', '_')
        lines.append(f"tdfol_counter{{name=\"{safe_name}\"}} {value}")
    
    # Memory metrics
    memory_stats = collector_stats.get('memory', {})
    for operation_name, stats in memory_stats.items():
        if isinstance(stats, dict) and 'mean' in stats:
            safe_name = operation_name.replace('.', '_').replace('-', '_')
            lines.append(f"tdfol_memory_mean_mb{{operation=\"{safe_name}\"}} {stats['mean']}")
    
    return '\n'.join(lines)


# ============================================================================
# Tool Registration
# ============================================================================

# MCP tool metadata for discovery and registration
TDFOL_PERFORMANCE_TOOLS = [
    {
        "name": "get_tdfol_metrics",
        "description": "Get current TDFOL performance metrics",
        "function": get_tdfol_metrics,
        "parameters": {},
        "category": "dashboard_tools"
    },
    {
        "name": "profile_tdfol_operation",
        "description": "Profile a TDFOL proving operation with detailed metrics",
        "function": profile_tdfol_operation,
        "parameters": {
            "formula_str": {"type": "string", "required": True},
            "kb_formulas": {"type": "array", "required": False},
            "runs": {"type": "integer", "default": 10},
            "strategy": {"type": "string", "required": False}
        },
        "category": "dashboard_tools"
    },
    {
        "name": "generate_tdfol_dashboard",
        "description": "Generate interactive HTML performance dashboard",
        "function": generate_tdfol_dashboard,
        "parameters": {
            "output_path": {"type": "string", "required": False},
            "include_profiling": {"type": "boolean", "default": False}
        },
        "category": "dashboard_tools"
    },
    {
        "name": "export_tdfol_statistics",
        "description": "Export TDFOL performance statistics in various formats",
        "function": export_tdfol_statistics,
        "parameters": {
            "format": {"type": "string", "default": "json"},
            "include_raw_data": {"type": "boolean", "default": False}
        },
        "category": "dashboard_tools"
    },
    {
        "name": "get_tdfol_profiler_report",
        "description": "Get detailed profiler report with bottlenecks",
        "function": get_tdfol_profiler_report,
        "parameters": {
            "report_format": {"type": "string", "default": "text"},
            "top_n": {"type": "integer", "default": 20}
        },
        "category": "dashboard_tools"
    },
    {
        "name": "compare_tdfol_strategies",
        "description": "Compare performance across different proving strategies",
        "function": compare_tdfol_strategies,
        "parameters": {
            "formula_str": {"type": "string", "required": True},
            "strategies": {"type": "array", "required": False},
            "kb_formulas": {"type": "array", "required": False},
            "runs_per_strategy": {"type": "integer", "default": 10}
        },
        "category": "dashboard_tools"
    },
    {
        "name": "check_tdfol_performance_regression",
        "description": "Check for performance regressions against baseline",
        "function": check_tdfol_performance_regression,
        "parameters": {
            "baseline_path": {"type": "string", "required": False},
            "threshold_percent": {"type": "number", "default": 10.0}
        },
        "category": "dashboard_tools"
    },
    {
        "name": "reset_tdfol_metrics",
        "description": "Reset TDFOL performance metrics and collectors",
        "function": reset_tdfol_metrics,
        "parameters": {},
        "category": "dashboard_tools"
    }
]


def get_tools() -> List[Dict[str, Any]]:
    """Get all TDFOL performance tools for MCP registration."""
    return TDFOL_PERFORMANCE_TOOLS


# Export for direct import
__all__ = [
    'get_tdfol_metrics',
    'profile_tdfol_operation',
    'generate_tdfol_dashboard',
    'export_tdfol_statistics',
    'get_tdfol_profiler_report',
    'compare_tdfol_strategies',
    'check_tdfol_performance_regression',
    'reset_tdfol_metrics',
    'get_tools',
    'TDFOL_PERFORMANCE_TOOLS'
]
