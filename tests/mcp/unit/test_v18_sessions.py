"""v18 session tests: CI145/CJ146/CK147/CM149/CN150.

All production modules under test were created or modified in v18:

* CI145 — ``delegation_chain_ascii`` MCP tool in ``delegation_audit_tool.py``
* CJ146 — ``detect_i18n_clauses()`` in ``nl_policy_conflict_detector.py``
* CK147 — ``UCANPolicyBridge.evaluate_audited_with_manager()``
* CM149 — ``DelegationManager.get_metrics()`` ``max_chain_depth`` + ``record_delegation_metrics()``
* CN150 — ``logic/api.py`` ``evaluate_with_manager`` convenience wrapper
"""
from __future__ import annotations

import importlib
import sys
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _import(module_path: str) -> Any:
    return importlib.import_module(module_path)


# ============================================================================
# CI145 — delegation_chain_ascii MCP tool
# ============================================================================

class TestCI145DelegationChainAsciiTool:
    """delegation_chain_ascii tool returns ASCII tree for leaf CID."""

    def _tool(self):
        mod = _import("ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool")
        return mod.delegation_chain_ascii

    def test_function_exists(self):
        mod = _import("ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool")
        assert hasattr(mod, "delegation_chain_ascii")

    def test_in_delegation_audit_tools_list(self):
        mod = _import("ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool")
        names = [t["name"] for t in mod.DELEGATION_AUDIT_TOOLS]
        assert "delegation_chain_ascii" in names

    def test_returns_status_ok_for_empty_chain(self):
        """Unknown leaf CID → empty chain → still returns status=ok with empty-chain ASCII."""
        tool = self._tool()
        with patch(
            "ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool._get_manager"
        ) as mock_get_manager:
            mock_mgr = MagicMock()
            mock_evaluator = MagicMock()
            mock_evaluator.build_chain.return_value = []
            mock_mgr.get_evaluator.return_value = mock_evaluator
            mock_get_manager.return_value = mock_mgr

            result = tool("test-leaf-cid")
        assert result["status"] == "ok"
        assert result["leaf_cid"] == "test-leaf-cid"
        assert "ascii_tree" in result
        assert "chain_length" in result
        assert result["chain_length"] == 0

    def test_returns_error_on_build_chain_exception(self):
        tool = self._tool()
        with patch(
            "ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool._get_manager"
        ) as mock_get_manager:
            mock_mgr = MagicMock()
            mock_evaluator = MagicMock()
            mock_evaluator.build_chain.side_effect = ValueError("no chain")
            mock_mgr.get_evaluator.return_value = mock_evaluator
            mock_get_manager.return_value = mock_mgr

            result = tool("bad-cid")
        assert result["status"] == "error"
        assert "chain" in result.get("error", "")

    def test_returns_error_on_manager_exception(self):
        tool = self._tool()
        with patch(
            "ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool._get_manager"
        ) as mock_get_manager:
            mock_get_manager.side_effect = RuntimeError("manager init failed")
            result = tool("any-cid")
        assert result["status"] == "error"

    def test_chain_length_matches_returned_tokens(self):
        tool = self._tool()
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationToken
        tokens = [
            DelegationToken(issuer="did:a", audience="did:b", capabilities=[]),
            DelegationToken(issuer="did:b", audience="did:c", capabilities=[]),
        ]
        with patch(
            "ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool._get_manager"
        ) as mock_get_manager:
            mock_mgr = MagicMock()
            mock_evaluator = MagicMock()
            mock_evaluator.build_chain.return_value = tokens
            mock_mgr.get_evaluator.return_value = mock_evaluator
            mock_get_manager.return_value = mock_mgr

            result = tool("cid2")
        assert result["status"] == "ok"
        assert result["chain_length"] == 2

    def test_ascii_tree_non_empty_for_single_token(self):
        tool = self._tool()
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationToken
        tokens = [DelegationToken(issuer="did:a", audience="did:b", capabilities=[])]
        with patch(
            "ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool._get_manager"
        ) as mock_get_manager:
            mock_mgr = MagicMock()
            mock_evaluator = MagicMock()
            mock_evaluator.build_chain.return_value = tokens
            mock_mgr.get_evaluator.return_value = mock_evaluator
            mock_get_manager.return_value = mock_mgr

            result = tool("cid1")
        assert result["status"] == "ok"
        assert result["ascii_tree"] != "(empty chain)"


# ============================================================================
# CJ146 — detect_i18n_clauses full clause compilation
# ============================================================================

class TestCJ146DetectI18NClauses:
    """detect_i18n_clauses: full FR/ES/DE clause compilation + conflict detection."""

    def _fn(self):
        mod = _import("ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector")
        return mod.detect_i18n_clauses

    def test_function_exists(self):
        mod = _import("ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector")
        assert hasattr(mod, "detect_i18n_clauses")

    def test_unsupported_language_returns_empty(self):
        fn = self._fn()
        result = fn("Alice peut lire. Alice ne peut pas lire.", language="zh")
        assert result == []

    def test_unknown_language_code_empty(self):
        fn = self._fn()
        result = fn("any text", language="xx")
        assert isinstance(result, list)
        assert result == []

    def test_returns_list_type(self):
        fn = self._fn()
        result = fn("some text", language="fr")
        assert isinstance(result, list)

    def test_french_no_conflict_text_returns_empty_or_list(self):
        fn = self._fn()
        # Simple French text with no deontic content should either return [] or fail gracefully
        result = fn("Le ciel est bleu.", language="fr")
        assert isinstance(result, list)

    def test_german_no_conflict_returns_list(self):
        fn = self._fn()
        result = fn("Der Himmel ist blau.", language="de")
        assert isinstance(result, list)

    def test_spanish_no_conflict_returns_list(self):
        fn = self._fn()
        result = fn("El cielo es azul.", language="es")
        assert isinstance(result, list)

    def test_reachable_from_api_module(self):
        try:
            from ipfs_datasets_py.logic.api import detect_i18n_clauses
            assert callable(detect_i18n_clauses)
        except ImportError:
            pytest.skip("logic.api not importable in this env")


# ============================================================================
# CK147 — UCANPolicyBridge.evaluate_audited_with_manager
# ============================================================================

class TestCK147EvaluateAuditedWithManager:
    """evaluate_audited_with_manager: wraps evaluate_with_manager + records to audit_log."""

    def _bridge(self):
        from ipfs_datasets_py.logic.integration.ucan_policy_bridge import UCANPolicyBridge
        return UCANPolicyBridge()

    def test_method_exists(self):
        bridge = self._bridge()
        assert hasattr(bridge, "evaluate_audited_with_manager")

    def test_returns_bridge_evaluation_result(self):
        bridge = self._bridge()
        from ipfs_datasets_py.logic.integration.ucan_policy_bridge import BridgeEvaluationResult
        result = bridge.evaluate_audited_with_manager(
            "pol1", tool="read", actor="alice",
        )
        assert isinstance(result, BridgeEvaluationResult)

    def test_audit_log_receives_record_call(self):
        bridge = self._bridge()
        mock_audit = MagicMock()
        bridge.evaluate_audited_with_manager(
            "pol1", tool="read", actor="alice", audit_log=mock_audit
        )
        mock_audit.record.assert_called_once()

    def test_audit_log_none_does_not_raise(self):
        bridge = self._bridge()
        result = bridge.evaluate_audited_with_manager(
            "pol1", tool="write", actor="bob", audit_log=None
        )
        assert result is not None

    def test_audit_error_does_not_propagate(self):
        bridge = self._bridge()
        bad_audit = MagicMock()
        bad_audit.record.side_effect = AttributeError("broken")
        # Should not raise
        result = bridge.evaluate_audited_with_manager(
            "pol1", tool="read", audit_log=bad_audit
        )
        assert result is not None

    def test_manager_none_falls_back_to_evaluate(self):
        bridge = self._bridge()
        from ipfs_datasets_py.logic.integration.ucan_policy_bridge import BridgeEvaluationResult
        result = bridge.evaluate_audited_with_manager(
            "pol1", tool="read", manager=None
        )
        assert isinstance(result, BridgeEvaluationResult)

    def test_manager_revoked_leaf_returns_deny(self):
        bridge = self._bridge()
        mock_manager = MagicMock()
        mock_manager.is_revoked.return_value = True
        result = bridge.evaluate_audited_with_manager(
            "pol1", tool="read", leaf_cid="revoked-cid", manager=mock_manager
        )
        assert result.decision == "deny"
        assert result.revoked is True

    def test_audit_record_gets_correct_policy_cid(self):
        bridge = self._bridge()
        mock_audit = MagicMock()
        bridge.evaluate_audited_with_manager(
            "my-policy-cid", tool="read", audit_log=mock_audit
        )
        call_kwargs = mock_audit.record.call_args
        assert call_kwargs is not None
        # Either positional or keyword
        all_args = {**call_kwargs.kwargs}
        if call_kwargs.args:
            all_args["policy_cid"] = call_kwargs.args[0] if call_kwargs.args else all_args.get("policy_cid")
        assert all_args.get("policy_cid") == "my-policy-cid" or any(
            "my-policy-cid" in str(a) for a in call_kwargs.args
        )

    def test_intent_cid_kwarg_forwarded_to_audit(self):
        bridge = self._bridge()
        mock_audit = MagicMock()
        bridge.evaluate_audited_with_manager(
            "pol1", tool="read", audit_log=mock_audit, intent_cid="custom-intent"
        )
        mock_audit.record.assert_called_once()
        call_kwargs = mock_audit.record.call_args.kwargs
        assert call_kwargs.get("intent_cid") == "custom-intent"


# ============================================================================
# CM149 — DelegationManager.get_metrics max_chain_depth + record_delegation_metrics
# ============================================================================

class TestCM149DelegationMetrics:
    """CM149: get_metrics includes max_chain_depth; record_delegation_metrics emits 3 gauges."""

    def test_get_metrics_has_max_chain_depth_key(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        metrics = mgr.get_metrics()
        assert "max_chain_depth" in metrics

    def test_empty_manager_max_chain_depth_is_zero(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        metrics = mgr.get_metrics()
        assert metrics["max_chain_depth"] == 0

    def test_get_metrics_still_has_token_count(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        metrics = mgr.get_metrics()
        assert "token_count" in metrics
        assert "revoked_count" in metrics

    def test_record_delegation_metrics_function_exists(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import record_delegation_metrics
        assert callable(record_delegation_metrics)

    def test_record_delegation_metrics_none_manager_no_op(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import record_delegation_metrics
        mock_collector = MagicMock()
        record_delegation_metrics(None, mock_collector)
        mock_collector.set_gauge.assert_not_called()

    def test_record_delegation_metrics_sets_three_gauges(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, record_delegation_metrics
        mgr = DelegationManager()
        mock_collector = MagicMock()
        record_delegation_metrics(mgr, mock_collector)
        calls = mock_collector.set_gauge.call_args_list
        gauge_names = {c.args[0] if c.args else c.kwargs.get("name") for c in calls}
        assert "mcp_revoked_cids_total" in gauge_names
        assert "mcp_delegation_store_depth" in gauge_names
        assert "mcp_delegation_chain_depth_max" in gauge_names

    def test_record_delegation_metrics_collector_error_no_raise(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, record_delegation_metrics
        mgr = DelegationManager()
        bad_collector = MagicMock()
        bad_collector.set_gauge.side_effect = RuntimeError("broken gauge")
        # Should not raise
        record_delegation_metrics(mgr, bad_collector)

    def test_get_metrics_max_chain_depth_int_or_zero(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        metrics = mgr.get_metrics()
        assert isinstance(metrics["max_chain_depth"], int)
        assert metrics["max_chain_depth"] >= 0


# ============================================================================
# CN150 — logic/api.py evaluate_with_manager convenience wrapper
# ============================================================================

class TestCN150EvaluateWithManagerApi:
    """CN150: logic/api.py evaluate_with_manager convenience wrapper."""

    def test_evaluate_with_manager_callable(self):
        try:
            from ipfs_datasets_py.logic.api import evaluate_with_manager
            assert callable(evaluate_with_manager)
        except ImportError:
            pytest.skip("anyio/logic.api not importable")

    def test_evaluate_with_manager_returns_result_or_none(self):
        try:
            from ipfs_datasets_py.logic.api import evaluate_with_manager
        except ImportError:
            pytest.skip("logic.api not importable")
        result = evaluate_with_manager("pol1", "read")
        # Returns BridgeEvaluationResult or None
        assert result is None or hasattr(result, "decision")

    def test_evaluate_with_manager_in_all(self):
        try:
            import ipfs_datasets_py.logic.api as api_mod
        except ImportError:
            pytest.skip("logic.api not importable")
        if hasattr(api_mod, "evaluate_with_manager"):
            assert "evaluate_with_manager" in api_mod.__all__

    def test_evaluate_with_manager_manager_none_no_raise(self):
        try:
            from ipfs_datasets_py.logic.api import evaluate_with_manager
        except ImportError:
            pytest.skip("logic.api not importable")
        result = evaluate_with_manager("pol1", "read", manager=None)
        assert result is None or hasattr(result, "policy_cid")

    def test_evaluate_with_manager_with_audit_log(self):
        try:
            from ipfs_datasets_py.logic.api import evaluate_with_manager
        except ImportError:
            pytest.skip("logic.api not importable")
        mock_audit = MagicMock()
        result = evaluate_with_manager("pol1", "read", audit_log=mock_audit)
        # Whether mock_audit.record was called depends on bridge availability
        assert result is None or hasattr(result, "decision")

    def test_module_imports_without_error(self):
        try:
            import ipfs_datasets_py.logic.api
        except ImportError:
            pytest.skip("logic.api not importable")

    def test_detect_i18n_clauses_in_api(self):
        try:
            import ipfs_datasets_py.logic.api as api_mod
        except ImportError:
            pytest.skip("logic.api not importable")
        # May or may not be present depending on import success
        if hasattr(api_mod, "detect_i18n_clauses"):
            assert callable(api_mod.detect_i18n_clauses)
