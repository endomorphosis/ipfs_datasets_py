"""
TDFOL Performance Dashboard Tool for MCP Server (thin wrapper).

Business logic lives in tdfol_performance_engine.TDFOLPerformanceEngine.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .tdfol_performance_engine import TDFOLPerformanceEngine

logger = logging.getLogger(__name__)

_engine = TDFOLPerformanceEngine()


def get_tdfol_metrics() -> Dict[str, Any]:
    """Get current TDFOL performance metrics."""
    return _engine.get_metrics()


def profile_tdfol_operation(
    formula_str: str,
    kb_formulas: Optional[List[str]] = None,
    runs: int = 10,
    strategy: Optional[str] = None,
) -> Dict[str, Any]:
    """Profile a TDFOL proving operation."""
    return _engine.profile_operation(formula_str, kb_formulas, runs, strategy)


def generate_tdfol_dashboard(
    output_path: Optional[str] = None,
    include_profiling: bool = False,
) -> Dict[str, Any]:
    """Generate TDFOL performance dashboard HTML."""
    return _engine.generate_dashboard(output_path, include_profiling)


def export_tdfol_statistics(
    format: str = "json",
    include_raw_data: bool = False,
) -> Dict[str, Any]:
    """Export TDFOL performance statistics."""
    return _engine.export_statistics(format, include_raw_data)


def get_tdfol_profiler_report(
    report_format: str = "text",
    top_n: int = 20,
) -> Dict[str, Any]:
    """Get detailed TDFOL profiler report."""
    return _engine.get_profiler_report(report_format, top_n)


def compare_tdfol_strategies(
    formula_str: str,
    strategies: Optional[List[str]] = None,
    kb_formulas: Optional[List[str]] = None,
    runs_per_strategy: int = 10,
) -> Dict[str, Any]:
    """Compare TDFOL proving strategies performance."""
    return _engine.compare_strategies(formula_str, strategies, kb_formulas, runs_per_strategy)


def check_tdfol_performance_regression(
    baseline_path: Optional[str] = None,
    threshold_percent: float = 10.0,
) -> Dict[str, Any]:
    """Check for TDFOL performance regressions."""
    return _engine.check_regression(baseline_path, threshold_percent)


def reset_tdfol_metrics() -> Dict[str, Any]:
    """Reset TDFOL performance metrics and collectors."""
    return _engine.reset_metrics()


TDFOL_PERFORMANCE_TOOLS = [
    {"name": "get_tdfol_metrics", "description": "Get current TDFOL performance metrics",
     "function": get_tdfol_metrics, "parameters": {}, "category": "dashboard_tools"},
    {"name": "profile_tdfol_operation",
     "description": "Profile a TDFOL proving operation with detailed metrics",
     "function": profile_tdfol_operation,
     "parameters": {"formula_str": {"type": "string", "required": True},
                    "kb_formulas": {"type": "array", "required": False},
                    "runs": {"type": "integer", "default": 10},
                    "strategy": {"type": "string", "required": False}},
     "category": "dashboard_tools"},
    {"name": "generate_tdfol_dashboard",
     "description": "Generate interactive HTML performance dashboard",
     "function": generate_tdfol_dashboard,
     "parameters": {"output_path": {"type": "string", "required": False},
                    "include_profiling": {"type": "boolean", "default": False}},
     "category": "dashboard_tools"},
    {"name": "export_tdfol_statistics",
     "description": "Export TDFOL performance statistics in various formats",
     "function": export_tdfol_statistics,
     "parameters": {"format": {"type": "string", "default": "json"},
                    "include_raw_data": {"type": "boolean", "default": False}},
     "category": "dashboard_tools"},
    {"name": "get_tdfol_profiler_report",
     "description": "Get detailed profiler report with bottlenecks",
     "function": get_tdfol_profiler_report,
     "parameters": {"report_format": {"type": "string", "default": "text"},
                    "top_n": {"type": "integer", "default": 20}},
     "category": "dashboard_tools"},
    {"name": "compare_tdfol_strategies",
     "description": "Compare performance across different proving strategies",
     "function": compare_tdfol_strategies,
     "parameters": {"formula_str": {"type": "string", "required": True},
                    "strategies": {"type": "array", "required": False},
                    "kb_formulas": {"type": "array", "required": False},
                    "runs_per_strategy": {"type": "integer", "default": 10}},
     "category": "dashboard_tools"},
    {"name": "check_tdfol_performance_regression",
     "description": "Check for performance regressions against baseline",
     "function": check_tdfol_performance_regression,
     "parameters": {"baseline_path": {"type": "string", "required": False},
                    "threshold_percent": {"type": "number", "default": 10.0}},
     "category": "dashboard_tools"},
    {"name": "reset_tdfol_metrics",
     "description": "Reset TDFOL performance metrics and collectors",
     "function": reset_tdfol_metrics, "parameters": {}, "category": "dashboard_tools"},
]


def get_tools() -> List[Dict[str, Any]]:
    """Get all TDFOL performance tools for MCP registration."""
    return TDFOL_PERFORMANCE_TOOLS


__all__ = [
    "get_tdfol_metrics",
    "profile_tdfol_operation",
    "generate_tdfol_dashboard",
    "export_tdfol_statistics",
    "get_tdfol_profiler_report",
    "compare_tdfol_strategies",
    "check_tdfol_performance_regression",
    "reset_tdfol_metrics",
    "get_tools",
    "TDFOL_PERFORMANCE_TOOLS",
]
