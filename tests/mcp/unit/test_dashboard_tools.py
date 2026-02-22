"""Unit tests for dashboard_tools/tdfol_performance_tool (Phase B2 session 33).

Covers:
- get_tdfol_metrics: returns dict with metric info
- profile_tdfol_operation: profiles a formula evaluation
- export_tdfol_statistics: export stats in various formats
- reset_tdfol_metrics: clears metrics state
- get_tdfol_profiler_report: report generation
"""
from __future__ import annotations

import pytest


class TestGetTdfolMetrics:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            get_tdfol_metrics,
        )
        r = get_tdfol_metrics()
        assert isinstance(r, dict)

    def test_non_empty(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            get_tdfol_metrics,
        )
        r = get_tdfol_metrics()
        assert len(r) > 0

    def test_consistent_repeated_calls(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            get_tdfol_metrics,
        )
        r1 = get_tdfol_metrics()
        r2 = get_tdfol_metrics()
        assert type(r1) == type(r2) == dict


class TestProfileTdfolOperation:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            profile_tdfol_operation,
        )
        r = profile_tdfol_operation("O(a)", [], runs=1)
        assert isinstance(r, dict)

    def test_strategy_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            profile_tdfol_operation,
        )
        r = profile_tdfol_operation("P(b)", [], runs=1, strategy="default")
        assert isinstance(r, dict)

    def test_empty_kb_formulas_handled(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            profile_tdfol_operation,
        )
        r = profile_tdfol_operation("", [])
        assert isinstance(r, dict)


class TestExportTdfolStatistics:
    def test_returns_dict_or_string(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            export_tdfol_statistics,
        )
        r = export_tdfol_statistics("json")
        assert isinstance(r, (dict, str))

    def test_csv_format_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            export_tdfol_statistics,
        )
        r = export_tdfol_statistics("csv")
        assert isinstance(r, (dict, str))

    def test_include_raw_data_param(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            export_tdfol_statistics,
        )
        r = export_tdfol_statistics("json", include_raw_data=True)
        assert isinstance(r, (dict, str))


class TestResetTdfolMetrics:
    def test_returns_dict(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            reset_tdfol_metrics,
        )
        r = reset_tdfol_metrics()
        assert isinstance(r, dict)


class TestGetTdfolProfilerReport:
    def test_returns_dict_or_string(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            get_tdfol_profiler_report,
        )
        r = get_tdfol_profiler_report("text")
        assert isinstance(r, (dict, str))

    def test_top_n_param_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.dashboard_tools.tdfol_performance_tool import (
            get_tdfol_profiler_report,
        )
        r = get_tdfol_profiler_report("text", top_n=5)
        assert isinstance(r, (dict, str))
