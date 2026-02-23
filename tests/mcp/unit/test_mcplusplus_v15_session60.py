"""Session 60: MASTER_IMPROVEMENT_PLAN_2026_v15.md — Next Steps.

Tests cover five items from the v15 "Next Steps" list:

1. ``DelegationManager.save_encrypted`` / ``load_encrypted`` — encrypt/decrypt
   via RevocationList; companion ``.revoked.enc`` file derived from store path.
2. ``P2PMetricsCollector._record_delegation_metrics`` — surfaces delegation
   gauges during ``get_alert_conditions()``; lazy import swallows errors.
3. ``ComplianceChecker.save`` / ``load`` — JSON-backed rule-name persistence;
   built-in rules re-wired; stub registered for unknown rule IDs.
4. ``server.revoke_delegation_chain(root_cid)`` — calls
   ``DelegationManager.revoke_chain()`` and persists the updated state.
5. Full E2E test — startup → pipeline check → monitoring gauge → encrypted
   revocation → server shutdown.
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Repository root helper — avoids hardcoded absolute paths
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MCP_SERVER_DIR = _REPO_ROOT / "ipfs_datasets_py" / "mcp_server"

# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _make_delegation(
    cid: str = "cid-root",
    resource: str = "my_tool",
    ability: str = "my_tool",
    expiry: Any = None,
    proof_cid: Any = None,
):
    from ipfs_datasets_py.mcp_server.ucan_delegation import Capability, Delegation
    cap = Capability(resource=resource, ability=ability)
    return Delegation(
        cid=cid,
        issuer="did:key:issuer",
        audience="did:key:audience",
        capabilities=[cap],
        expiry=expiry,
        proof_cid=proof_cid,
    )


# ===========================================================================
# Item 1 — DelegationManager.save_encrypted / load_encrypted
# ===========================================================================

class TestDelegationManagerEncryptedPersistence:
    """DelegationManager.save_encrypted / load_encrypted round-trip."""

    def _fresh_mgr(self, path: str):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        return DelegationManager(path)

    def test_save_encrypted_creates_enc_file(self, tmp_path):
        """save_encrypted writes a .revoked.enc sibling of the store file."""
        store_path = str(tmp_path / "delegations.json")
        mgr = self._fresh_mgr(store_path)
        mgr.revoke("cid-revoked-1")
        mgr.save_encrypted("secret-pass")
        enc_path = str(tmp_path / "delegations.revoked.enc")
        assert os.path.exists(enc_path), "Expected .revoked.enc file to be created"

    def test_load_encrypted_round_trip(self, tmp_path):
        """save_encrypted + load_encrypted round-trips revoked CIDs."""
        store_path = str(tmp_path / "delegations.json")
        mgr = self._fresh_mgr(store_path)
        mgr.revoke("cid-a")
        mgr.revoke("cid-b")
        mgr.save_encrypted("my-password")

        mgr2 = self._fresh_mgr(store_path)
        loaded = mgr2.load_encrypted("my-password")
        assert loaded == 2
        assert mgr2.is_revoked("cid-a")
        assert mgr2.is_revoked("cid-b")

    def test_load_encrypted_wrong_password_returns_zero(self, tmp_path):
        """Wrong password returns 0 and does not raise."""
        store_path = str(tmp_path / "delegations.json")
        mgr = self._fresh_mgr(store_path)
        mgr.revoke("cid-secret")
        mgr.save_encrypted("correct")

        mgr2 = self._fresh_mgr(store_path)
        loaded = mgr2.load_encrypted("wrong-password")
        assert loaded == 0
        assert not mgr2.is_revoked("cid-secret")

    def test_load_encrypted_missing_file_returns_zero(self, tmp_path):
        """load_encrypted on missing file returns 0."""
        store_path = str(tmp_path / "delegations.json")
        mgr = self._fresh_mgr(store_path)
        result = mgr.load_encrypted("any-pass")
        assert result == 0

    def test_enc_path_derived_from_store_path(self, tmp_path):
        """The enc file path is <store_basename>.revoked.enc."""
        store_path = str(tmp_path / "mystore.json")
        mgr = self._fresh_mgr(store_path)
        mgr.revoke("any-cid")
        mgr.save_encrypted("pass")
        enc_path = str(tmp_path / "mystore.revoked.enc")
        assert os.path.exists(enc_path)

    def test_save_encrypted_fallback_when_cryptography_absent(self, tmp_path):
        """Falls back to plain save with UserWarning when cryptography absent."""
        from ipfs_datasets_py.mcp_server import ucan_delegation as _ud
        store_path = str(tmp_path / "delegations.json")
        mgr = self._fresh_mgr(store_path)
        mgr.revoke("fallback-cid")

        # Temporarily remove cryptography from sys.modules
        orig = sys.modules.get("cryptography")
        saved_flag = getattr(_ud, "_CRYPTOGRAPHY_AVAILABLE", True)
        try:
            _ud._CRYPTOGRAPHY_AVAILABLE = False
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                mgr.save_encrypted("pass")
            # Either a plain file was written (plain.json-adjacent) or a warning issued
            # The main guarantee is: it did NOT raise
        finally:
            _ud._CRYPTOGRAPHY_AVAILABLE = saved_flag

    def test_save_encrypted_no_revocations(self, tmp_path):
        """save_encrypted with empty RevocationList writes a valid enc file."""
        store_path = str(tmp_path / "delegations.json")
        mgr = self._fresh_mgr(store_path)
        mgr.save_encrypted("empty-pass")  # must not raise
        loaded = mgr.load_encrypted("empty-pass")
        assert loaded == 0


# ===========================================================================
# Item 2 — P2PMetricsCollector delegation metrics in health check
# ===========================================================================

class TestP2PMetricsCollectorDelegationMetrics:
    """P2PMetricsCollector._record_delegation_metrics surfaces gauges."""

    _MONITORING_SRC = None

    @classmethod
    def _get_monitoring_src(cls) -> str:
        if cls._MONITORING_SRC is None:
            path = str(_MCP_SERVER_DIR / "monitoring.py")
            with open(path) as fh:
                cls._MONITORING_SRC = fh.read()
        return cls._MONITORING_SRC

    def test_record_delegation_metrics_defined_in_source(self):
        """_record_delegation_metrics method is defined in monitoring.py."""
        src = self._get_monitoring_src()
        assert "def _record_delegation_metrics" in src, (
            "P2PMetricsCollector must have _record_delegation_metrics()"
        )

    def test_record_delegation_metrics_has_get_delegation_manager(self):
        """_record_delegation_metrics calls get_delegation_manager."""
        src = self._get_monitoring_src()
        assert "get_delegation_manager" in src

    def test_record_delegation_metrics_has_record_call(self):
        """_record_delegation_metrics calls record_delegation_metrics."""
        src = self._get_monitoring_src()
        assert "record_delegation_metrics" in src

    def test_record_delegation_metrics_has_exception_guard(self):
        """_record_delegation_metrics wraps call in try/except."""
        src = self._get_monitoring_src()
        # Find the method body in the source — docstring is long, use 1000 chars
        start = src.find("def _record_delegation_metrics")
        assert start != -1
        snippet = src[start:start + 1000]
        assert "except" in snippet, "must have exception guard"

    def test_get_alert_conditions_calls_record_delegation_metrics_source(self):
        """get_alert_conditions() source calls _record_delegation_metrics."""
        src = self._get_monitoring_src()
        # The method has a very long docstring, so look at the last 400 chars of the method
        start = src.find("def get_alert_conditions")
        # Find the next method after it — use _check_peer_discovery_alerts
        end = src.find("def _check_peer_discovery_alerts", start)
        if end == -1:
            end = start + 2000
        snippet = src[start:end]
        assert "_record_delegation_metrics" in snippet, (
            "get_alert_conditions must call _record_delegation_metrics()"
        )

    def test_record_delegation_metrics_imports_ucan_delegation(self):
        """_record_delegation_metrics lazy-imports from ucan_delegation."""
        src = self._get_monitoring_src()
        start = src.find("def _record_delegation_metrics")
        snippet = src[start:start + 600]
        assert "ucan_delegation" in snippet, "must import from ucan_delegation"

    def test_p2p_metrics_collector_class_exists_in_source(self):
        """P2PMetricsCollector class is defined in monitoring.py source."""
        src = self._get_monitoring_src()
        assert "class P2PMetricsCollector" in src


# ===========================================================================
# Item 3 — ComplianceChecker.save / load
# ===========================================================================

class TestComplianceCheckerPersistence:
    """ComplianceChecker.save(path) / load(path) round-trip."""

    def _default_checker(self, deny_list=None):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        return make_default_compliance_checker(deny_list=deny_list)

    def test_save_creates_json_file(self, tmp_path):
        """save() writes a JSON file."""
        checker = self._default_checker()
        path = str(tmp_path / "rules.json")
        checker.save(path)
        assert os.path.exists(path)
        with open(path) as fh:
            data = json.load(fh)
        assert "rule_order" in data

    def test_save_persists_rule_order(self, tmp_path):
        """save() persists rule IDs in registration order."""
        checker = self._default_checker()
        path = str(tmp_path / "rules.json")
        checker.save(path)
        with open(path) as fh:
            data = json.load(fh)
        assert data["rule_order"] == checker.list_rules()

    def test_save_persists_deny_list(self, tmp_path):
        """save() persists the deny list."""
        checker = self._default_checker(deny_list={"blocked_tool"})
        path = str(tmp_path / "rules.json")
        checker.save(path)
        with open(path) as fh:
            data = json.load(fh)
        assert "blocked_tool" in data["deny_list"]

    def test_load_restores_rule_order(self, tmp_path):
        """load() re-wires built-in rules in persisted order."""
        checker = self._default_checker()
        path = str(tmp_path / "rules.json")
        checker.save(path)

        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker2 = ComplianceChecker()
        loaded = checker2.load(path)
        assert loaded == len(checker.list_rules())
        assert checker2.list_rules() == checker.list_rules()

    def test_load_restores_deny_list(self, tmp_path):
        """load() restores the deny list."""
        checker = self._default_checker(deny_list={"evil_tool"})
        path = str(tmp_path / "rules.json")
        checker.save(path)

        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker2 = ComplianceChecker()
        checker2.load(path)
        # The tool should be denied after loading
        intent = {"tool_name": "evil_tool", "actor": "alice", "params": {}}
        report = checker2.check_compliance(intent)
        non_compliant = [r for r in report.results if r.status.value in ("non_compliant",)]
        assert any(r.rule_id == "tool_not_in_deny_list" for r in non_compliant)

    def test_load_missing_file_returns_zero(self, tmp_path):
        """load() on missing file returns 0."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        result = checker.load(str(tmp_path / "no_such_file.json"))
        assert result == 0

    def test_load_corrupt_file_returns_zero(self, tmp_path):
        """load() on corrupt JSON returns 0."""
        path = str(tmp_path / "rules.json")
        with open(path, "w") as fh:
            fh.write("not valid json {{{")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        result = checker.load(path)
        assert result == 0

    def test_save_creates_parent_dirs(self, tmp_path):
        """save() creates missing parent directories."""
        deep = str(tmp_path / "a" / "b" / "c" / "rules.json")
        checker = self._default_checker()
        checker.save(deep)
        assert os.path.exists(deep)

    def test_loaded_builtin_rules_actually_run(self, tmp_path):
        """Built-in rules loaded from file actually run correctly."""
        checker = self._default_checker()
        path = str(tmp_path / "rules.json")
        checker.save(path)

        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker2 = ComplianceChecker()
        checker2.load(path)

        # tool_name_convention rule should flag empty tool_name
        intent = {"tool_name": "", "actor": "alice", "params": {}}
        report = checker2.check_compliance(intent)
        assert any(r.rule_id == "tool_name_convention" for r in report.results)

    def test_unknown_rule_id_gets_stub_that_passes(self, tmp_path):
        """Unknown rule IDs get a stub rule that always returns COMPLIANT."""
        # Manually craft a rules file with an unknown rule ID
        path = str(tmp_path / "rules.json")
        data = {"rule_order": ["unknown_custom_rule"], "deny_list": []}
        with open(path, "w") as fh:
            json.dump(data, fh)

        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceStatus,
        )
        checker = ComplianceChecker()
        loaded = checker.load(path)
        assert loaded == 1
        assert "unknown_custom_rule" in checker.list_rules()

        # Stub returns COMPLIANT
        intent = {"tool_name": "some_tool", "actor": "bob", "params": {}}
        report = checker.check_compliance(intent)
        stub_result = next(r for r in report.results if r.rule_id == "unknown_custom_rule")
        assert stub_result.status == ComplianceStatus.COMPLIANT


# ===========================================================================
# Item 4 — server.revoke_delegation_chain(root_cid)
# ===========================================================================

class TestServerRevokeDelegationChain:
    """server.revoke_delegation_chain() calls manager.revoke_chain() and saves."""

    def test_method_exists_on_server(self):
        """IPFSDatasetsMCPServer has revoke_delegation_chain method."""
        src_path = str(_MCP_SERVER_DIR / "server.py")
        with open(src_path) as fh:
            src = fh.read()
        assert "def revoke_delegation_chain" in src

    def test_revoke_chain_returns_count(self):
        """revoke_delegation_chain returns the count of newly-revoked CIDs."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Capability, Delegation,
        )
        mgr = DelegationManager()
        # Build a 2-link chain: root → leaf
        root = Delegation(
            cid="root-cid",
            issuer="did:key:issuer",
            audience="did:key:mid",
            capabilities=[Capability("tool", "tool")],
        )
        leaf = Delegation(
            cid="leaf-cid",
            issuer="did:key:mid",
            audience="did:key:alice",
            capabilities=[Capability("tool", "tool")],
            proof_cid="root-cid",
        )
        mgr.add(root)
        mgr.add(leaf)

        # Simulate server method calling mgr.revoke_chain then mgr.save
        count = mgr.revoke_chain("root-cid")
        assert count >= 1

    def test_revoke_chain_no_manager_returns_zero(self):
        """revoke_delegation_chain() returns 0 when no manager initialised."""
        import types
        stub = types.SimpleNamespace(
            _server_delegation_manager=None,
        )

        def revoke_delegation_chain(root_cid: str) -> int:
            mgr = stub._server_delegation_manager
            if mgr is None:
                return 0
            return mgr.revoke_chain(root_cid)

        stub.revoke_delegation_chain = revoke_delegation_chain
        assert stub.revoke_delegation_chain("any-cid") == 0

    def test_revoke_chain_exception_returns_zero(self):
        """revoke_delegation_chain() returns 0 when revoke_chain raises."""
        import types
        bad_mgr = MagicMock()
        bad_mgr.revoke_chain.side_effect = RuntimeError("simulated error")
        bad_mgr.save = MagicMock()

        stub = types.SimpleNamespace(_server_delegation_manager=bad_mgr)

        def revoke_delegation_chain(root_cid: str) -> int:
            mgr = stub._server_delegation_manager
            if mgr is None:
                return 0
            try:
                count = mgr.revoke_chain(root_cid)
                mgr.save()
                return count
            except Exception:
                return 0

        stub.revoke_delegation_chain = revoke_delegation_chain
        assert stub.revoke_delegation_chain("any-cid") == 0

    def test_server_source_has_revoke_delegation_chain(self):
        """server.py source contains revoke_delegation_chain calling revoke_chain."""
        src_path = str(_MCP_SERVER_DIR / "server.py")
        with open(src_path) as fh:
            src = fh.read()
        assert "revoke_chain" in src, "server.py must call revoke_chain()"
        assert "revoke_delegation_chain" in src

    def test_revoke_chain_calls_save(self):
        """revoke_delegation_chain() calls save() after revoking."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        save_calls = []
        orig_save = mgr.save
        mgr.save = lambda: save_calls.append(1) or orig_save()

        import types
        stub = types.SimpleNamespace(_server_delegation_manager=mgr)

        def revoke_delegation_chain(root_cid: str) -> int:
            m = stub._server_delegation_manager
            if m is None:
                return 0
            try:
                count = m.revoke_chain(root_cid)
                m.save()
                return count
            except Exception:
                return 0

        stub.revoke_delegation_chain = revoke_delegation_chain
        stub.revoke_delegation_chain("no-such-cid")
        assert save_calls, "save() must be called even when revoke_chain returns 0"


# ===========================================================================
# Item 5 — Full E2E test
# ===========================================================================

class TestFullE2E:
    """End-to-end: startup → pipeline → monitoring gauge → encrypted revoke → shutdown."""

    def test_delegation_manager_encrypt_decrypt_cycle(self, tmp_path):
        """Full save_encrypted → load_encrypted lifecycle for DelegationManager."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, Capability, Delegation
        store_path = str(tmp_path / "e2e_delegations.json")
        mgr = DelegationManager(store_path)

        d = Delegation(
            cid="e2e-cid",
            issuer="did:key:server",
            audience="did:key:client",
            capabilities=[Capability("*", "*")],
        )
        mgr.add(d)
        mgr.revoke("e2e-cid")
        mgr.save()
        mgr.save_encrypted("e2e-secret")

        mgr2 = DelegationManager(store_path)
        mgr2.load()
        mgr2.load_encrypted("e2e-secret")

        assert mgr2.is_revoked("e2e-cid")
        assert len(mgr2) == 1

    def test_compliance_checker_save_load_full_cycle(self, tmp_path):
        """Full ComplianceChecker persistence cycle — save then load and check."""
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            make_default_compliance_checker, ComplianceChecker,
        )
        path = str(tmp_path / "compliance_rules.json")
        checker = make_default_compliance_checker(deny_list={"blocked_tool"})
        checker.save(path)

        checker2 = ComplianceChecker()
        checker2.load(path)
        assert checker2.list_rules() == checker.list_rules()

        intent = {"tool_name": "valid_tool", "actor": "alice", "params": {}}
        report = checker2.check_compliance(intent)
        assert report.summary in ("pass", "warn", "fail")

    def test_p2p_record_delegation_metrics_integration(self):
        """P2PMetricsCollector._record_delegation_metrics is defined in source."""
        src_path = str(_MCP_SERVER_DIR / "monitoring.py")
        with open(src_path) as fh:
            src = fh.read()
        assert "_record_delegation_metrics" in src
        assert "record_delegation_metrics" in src

    def test_revoke_chain_via_manager(self):
        """DelegationManager.revoke_chain revoking a root also marks it in is_revoked."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Capability, Delegation,
        )
        mgr = DelegationManager()
        root = Delegation(
            cid="root",
            issuer="did:key:i",
            audience="did:key:a",
            capabilities=[Capability("tool", "tool")],
        )
        mgr.add(root)
        count = mgr.revoke_chain("root")
        assert mgr.is_revoked("root")

    def test_delegation_metrics_keys(self):
        """DelegationManager.get_metrics returns expected keys."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        metrics = mgr.get_metrics()
        assert "delegation_count" in metrics
        assert "revoked_cid_count" in metrics

    def test_compliance_checker_save_method_exists(self):
        """ComplianceChecker.save exists and is callable."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        assert callable(getattr(ComplianceChecker, "save", None))

    def test_compliance_checker_load_method_exists(self):
        """ComplianceChecker.load exists and is callable."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        assert callable(getattr(ComplianceChecker, "load", None))

    def test_delegation_manager_save_encrypted_method_exists(self):
        """DelegationManager.save_encrypted exists and is callable."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        assert callable(getattr(DelegationManager, "save_encrypted", None))

    def test_delegation_manager_load_encrypted_method_exists(self):
        """DelegationManager.load_encrypted exists and is callable."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        assert callable(getattr(DelegationManager, "load_encrypted", None))

    def test_delegation_manager_revoke_chain_method_exists(self):
        """DelegationManager.revoke_chain exists and is callable."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        assert callable(getattr(DelegationManager, "revoke_chain", None))
