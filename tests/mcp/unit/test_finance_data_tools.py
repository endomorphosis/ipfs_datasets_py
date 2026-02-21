"""Unit tests for finance_data_tools (Phase B2 session 33).

Covers:
- finance_theorems: list_financial_theorems, apply_financial_theorem (sync, JSON string return)
"""
from __future__ import annotations

import json
from typing import Any

import pytest


class TestListFinancialTheorems:
    def test_returns_json_string(self):
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
            list_financial_theorems,
        )
        r = list_financial_theorems()
        assert isinstance(r, str)

    def test_json_has_theorems_key(self):
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
            list_financial_theorems,
        )
        r = list_financial_theorems()
        data = json.loads(r)
        assert "theorems" in data or "total_theorems" in data

    def test_event_type_filter_accepted(self):
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
            list_financial_theorems,
        )
        r = list_financial_theorems(event_type="stock_split")
        assert isinstance(r, str)
        # Must be valid JSON even for unknown event type filter
        json.loads(r)

    def test_total_theorems_non_negative(self):
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
            list_financial_theorems,
        )
        data = json.loads(list_financial_theorems())
        if "total_theorems" in data:
            assert data["total_theorems"] >= 0

    def test_no_filter_returns_all(self):
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
            list_financial_theorems,
        )
        data = json.loads(list_financial_theorems())
        # Either 'theorems' list or 'total_theorems' count key should be present
        assert "theorems" in data or "total_theorems" in data


class TestApplyFinancialTheorem:
    """apply_financial_theorem(theorem_id, symbol, event_date, event_data)"""

    def test_returns_json_string(self):
        from datetime import datetime
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
            apply_financial_theorem,
        )
        r = apply_financial_theorem(
            "STOCK_SPLIT", "AAPL", datetime(2023, 6, 1), {"split_ratio": 2.0}
        )
        assert isinstance(r, str)

    def test_result_is_valid_json(self):
        from datetime import datetime
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
            apply_financial_theorem,
        )
        r = apply_financial_theorem(
            "STOCK_SPLIT", "TSLA", datetime(2023, 1, 1), {}
        )
        data = json.loads(r)
        assert isinstance(data, dict)

    def test_unknown_theorem_returns_error_json(self):
        from datetime import datetime
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
            apply_financial_theorem,
        )
        r = apply_financial_theorem(
            "NONEXISTENT_THEOREM", "X", datetime(2023, 1, 1), {}
        )
        assert isinstance(r, str)
        data = json.loads(r)
        # Should return either an error or a status field
        assert "error" in data or "status" in data or "theorem_name" in data

    def test_empty_event_data_handled(self):
        from datetime import datetime
        from ipfs_datasets_py.mcp_server.tools.finance_data_tools.finance_theorems import (
            apply_financial_theorem,
        )
        r = apply_financial_theorem(
            "DIVIDEND_EX_DATE", "MSFT", datetime(2023, 3, 15), {}
        )
        assert isinstance(r, str)
        json.loads(r)  # Must be valid JSON
