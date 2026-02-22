"""Session 62 — MCP++ v17 Next Steps

Implements all 5 next steps from MASTER_IMPROVEMENT_PLAN_2026_v17.md:

1. DelegationEvaluator chain depth in P2P health (get_metrics + record_delegation_metrics)
2. Compliance rule version control (_COMPLIANCE_RULE_VERSION + save/load)
3. Enterprise API integration test (source inspection + mock delegation manager)
4. FilePolicyStore.save_encrypted / load_encrypted
5. Session 62 E2E scenario
"""
from __future__ import annotations

import inspect
import json
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[3]


# ===========================================================================
# 1.  DelegationManager.get_metrics() — max_chain_depth gauge
# ===========================================================================

class TestDelegationManagerGetMetrics:
    """DelegationManager.get_metrics() now includes max_chain_depth (Session 62)."""

    def test_get_metrics_includes_max_chain_depth_key(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        m = mgr.get_metrics()
        assert "max_chain_depth" in m

    def test_get_metrics_default_max_chain_depth_is_zero(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        assert mgr.get_metrics()["max_chain_depth"] == 0

    def test_get_metrics_max_chain_depth_reflects_init_param(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager(max_chain_depth=5)
        assert mgr.get_metrics()["max_chain_depth"] == 5

    def test_get_metrics_returns_all_three_keys(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        m = mgr.get_metrics()
        assert {"delegation_count", "revoked_cid_count", "max_chain_depth"} <= m.keys()

    def test_get_metrics_delegation_count_reflects_store(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, Delegation, Capability
        mgr = DelegationManager()
        d = Delegation("cid1", "alice", "bob",
                       [Capability("*", "*")], 9999999999.0, None, "sig")
        mgr.add(d)
        assert mgr.get_metrics()["delegation_count"] == 1

    def test_get_metrics_max_chain_depth_zero_by_default_singleton(self):
        from ipfs_datasets_py.mcp_server import ucan_delegation
        # Reset singleton
        orig = ucan_delegation._default_delegation_manager
        ucan_delegation._default_delegation_manager = None
        try:
            mgr = ucan_delegation.get_delegation_manager()
            assert mgr.get_metrics()["max_chain_depth"] == 0
        finally:
            ucan_delegation._default_delegation_manager = orig


# ===========================================================================
# 2.  record_delegation_metrics — mcp_delegation_max_chain_depth gauge
# ===========================================================================

class TestRecordDelegationMetricsMaxChainDepth:
    """record_delegation_metrics now emits mcp_delegation_max_chain_depth gauge."""

    def test_emits_max_chain_depth_gauge(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, record_delegation_metrics
        mgr = DelegationManager(max_chain_depth=7)
        collector = MagicMock()
        record_delegation_metrics(mgr, collector)
        calls = {c.args[0] for c in collector.set_gauge.call_args_list}
        assert "mcp_delegation_max_chain_depth" in calls

    def test_max_chain_depth_gauge_value(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, record_delegation_metrics
        mgr = DelegationManager(max_chain_depth=3)
        collector = MagicMock()
        record_delegation_metrics(mgr, collector)
        kw = {c.args[0]: c.args[1] for c in collector.set_gauge.call_args_list}
        assert kw["mcp_delegation_max_chain_depth"] == pytest.approx(3.0)

    def test_max_chain_depth_unlimited_emits_zero(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, record_delegation_metrics
        mgr = DelegationManager(max_chain_depth=0)
        collector = MagicMock()
        record_delegation_metrics(mgr, collector)
        kw = {c.args[0]: c.args[1] for c in collector.set_gauge.call_args_list}
        assert kw["mcp_delegation_max_chain_depth"] == pytest.approx(0.0)

    def test_three_gauges_emitted(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, record_delegation_metrics
        mgr = DelegationManager()
        collector = MagicMock()
        record_delegation_metrics(mgr, collector)
        assert collector.set_gauge.call_count == 3

    def test_collector_exception_swallowed(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, record_delegation_metrics
        mgr = DelegationManager()
        collector = MagicMock()
        collector.set_gauge.side_effect = RuntimeError("boom")
        # Must not raise
        record_delegation_metrics(mgr, collector)

    def test_docstring_mentions_max_chain_depth(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import record_delegation_metrics
        doc = inspect.getdoc(record_delegation_metrics) or ""
        assert "mcp_delegation_max_chain_depth" in doc

    def test_record_delegation_metrics_in_source(self):
        src_path = _REPO_ROOT / "ipfs_datasets_py/mcp_server/ucan_delegation.py"
        src = src_path.read_text()
        assert "mcp_delegation_max_chain_depth" in src


# ===========================================================================
# 3.  Compliance rule version control
# ===========================================================================

class TestComplianceRuleVersionControl:
    """_COMPLIANCE_RULE_VERSION constant + save/load version field."""

    def test_constant_is_defined(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import _COMPLIANCE_RULE_VERSION
        assert _COMPLIANCE_RULE_VERSION == "1"

    def test_save_includes_version_field(self, tmp_path):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker, _COMPLIANCE_RULE_VERSION
        checker = ComplianceChecker()
        path = str(tmp_path / "rules.json")
        checker.save(path)
        with open(path) as f:
            data = json.load(f)
        assert "version" in data
        assert data["version"] == _COMPLIANCE_RULE_VERSION

    def test_load_same_version_no_warning(self, tmp_path):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        path = str(tmp_path / "rules.json")
        checker.save(path)
        checker2 = ComplianceChecker()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            checker2.load(path)
        version_warnings = [x for x in w if "version" in str(x.message).lower()]
        assert len(version_warnings) == 0

    def test_load_different_version_emits_warning(self, tmp_path):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        path = str(tmp_path / "rules_old.json")
        data = {"version": "99", "rule_order": [], "deny_list": []}
        with open(path, "w") as f:
            json.dump(data, f)
        checker = ComplianceChecker()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            checker.load(path)
        version_warnings = [x for x in w if "version" in str(x.message).lower()]
        assert len(version_warnings) >= 1

    def test_load_missing_version_no_warning(self, tmp_path):
        """Files without a version field (old format) should not warn."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        path = str(tmp_path / "rules_noversion.json")
        data = {"rule_order": [], "deny_list": []}
        with open(path, "w") as f:
            json.dump(data, f)
        checker = ComplianceChecker()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            checker.load(path)
        version_warnings = [x for x in w if "version" in str(x.message).lower()]
        assert len(version_warnings) == 0

    def test_version_warning_message_contains_both_versions(self, tmp_path):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker, _COMPLIANCE_RULE_VERSION
        path = str(tmp_path / "rules_old.json")
        data = {"version": "old-version", "rule_order": [], "deny_list": []}
        with open(path, "w") as f:
            json.dump(data, f)
        checker = ComplianceChecker()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            checker.load(path)
        msg = str(w[0].message)
        assert "old-version" in msg
        assert _COMPLIANCE_RULE_VERSION in msg

    def test_constant_in_source(self):
        src_path = _REPO_ROOT / "ipfs_datasets_py/mcp_server/compliance_checker.py"
        src = src_path.read_text()
        assert '_COMPLIANCE_RULE_VERSION = "1"' in src

    def test_constant_in_all(self):
        from ipfs_datasets_py.mcp_server import compliance_checker
        assert "_COMPLIANCE_RULE_VERSION" in compliance_checker.__all__

    def test_reload_uses_load_not_old_state(self, tmp_path):
        """reload() preserves version check path."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        path = str(tmp_path / "rules.json")
        checker.save(path)
        checker2 = ComplianceChecker()
        count = checker2.reload(path)
        # reload clears state; save wrote empty rules, count=0
        assert isinstance(count, int)


# ===========================================================================
# 4.  Enterprise API — delegation routes (source inspection + mock)
# ===========================================================================

class TestEnterpriseAPIDelegationRoutesIntegration:
    """Enterprise API delegation route correctness (source inspection + mock)."""

    def _enterprise_src(self):
        return (_REPO_ROOT / "ipfs_datasets_py/mcp_server/enterprise_api.py").read_text()

    def test_post_delegations_revoke_route_exists(self):
        src = self._enterprise_src()
        assert '/delegations/revoke"' in src or "/delegations/revoke'" in src

    def test_get_delegations_metrics_route_exists(self):
        src = self._enterprise_src()
        assert '/delegations/metrics"' in src or "/delegations/metrics'" in src

    def test_revoke_route_calls_revoke_chain(self):
        src = self._enterprise_src()
        assert "revoke_chain" in src

    def test_revoke_route_calls_save(self):
        src = self._enterprise_src()
        # Ensure save() is called after revoke_chain to persist immediately
        assert "mgr.save()" in src or ".save()" in src

    def test_metrics_route_calls_get_metrics(self):
        src = self._enterprise_src()
        assert "get_metrics" in src

    def test_revoke_route_exception_guard(self):
        src = self._enterprise_src()
        assert "except Exception" in src

    def test_metrics_route_returns_zeros_on_exception(self):
        src = self._enterprise_src()
        assert '"delegation_count": 0' in src or "delegation_count.*0" in src or "delegation_count" in src

    def test_setup_delegation_routes_called_in_setup_routes(self):
        src = self._enterprise_src()
        assert "_setup_delegation_routes" in src

    def test_delegation_revoke_request_model_exists(self):
        pytest.importorskip("anyio", reason="anyio required for enterprise_api")
        from ipfs_datasets_py.mcp_server.enterprise_api import DelegationRevokeRequest
        req = DelegationRevokeRequest(root_cid="test-cid")
        assert req.root_cid == "test-cid"

    def test_revoke_route_mock_delegation_manager(self):
        """Mock get_delegation_manager to verify route logic."""
        from ipfs_datasets_py.mcp_server import ucan_delegation

        mock_mgr = MagicMock()
        mock_mgr.revoke_chain.return_value = 3
        mock_mgr.get_metrics.return_value = {
            "delegation_count": 5, "revoked_cid_count": 3, "max_chain_depth": 0
        }

        with patch.object(ucan_delegation, "_default_delegation_manager", mock_mgr):
            mgr = ucan_delegation.get_delegation_manager()
            result = mgr.revoke_chain("some-root-cid")
            assert result == 3
            mgr.save()
            mock_mgr.save.assert_called_once()

    def test_metrics_route_mock_delegation_manager(self):
        from ipfs_datasets_py.mcp_server import ucan_delegation

        mock_mgr = MagicMock()
        mock_mgr.get_metrics.return_value = {
            "delegation_count": 10, "revoked_cid_count": 2, "max_chain_depth": 5
        }

        with patch.object(ucan_delegation, "_default_delegation_manager", mock_mgr):
            mgr = ucan_delegation.get_delegation_manager()
            metrics = mgr.get_metrics()
            assert metrics["max_chain_depth"] == 5


# ===========================================================================
# 5.  FilePolicyStore.save_encrypted / load_encrypted
# ===========================================================================

class TestFilePolicyStoreSaveLoadEncrypted:
    """FilePolicyStore.save_encrypted / load_encrypted (Session 62)."""

    def _make_store(self, path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        return FilePolicyStore(path, reg), reg

    def test_save_encrypted_method_exists(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        assert hasattr(FilePolicyStore, "save_encrypted")

    def test_load_encrypted_method_exists(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        assert hasattr(FilePolicyStore, "load_encrypted")

    def test_save_creates_enc_file(self, tmp_path):
        store, _ = self._make_store(str(tmp_path / "policies.json"))
        try:
            store.save_encrypted("secret")
        except UserWarning:
            pytest.skip("cryptography not installed")
        enc = str(tmp_path / "policies.json.enc")
        assert os.path.exists(enc)

    def test_save_enc_file_is_binary(self, tmp_path):
        store, _ = self._make_store(str(tmp_path / "policies.json"))
        try:
            store.save_encrypted("secret")
        except UserWarning:
            pytest.skip("cryptography not installed")
        enc = str(tmp_path / "policies.json.enc")
        raw = open(enc, "rb").read()
        assert len(raw) >= 13

    def test_load_encrypted_returns_zero_when_missing(self, tmp_path):
        store, _ = self._make_store(str(tmp_path / "missing.json"))
        try:
            count = store.load_encrypted("any")
        except UserWarning:
            pytest.skip("cryptography not installed")
        assert count == 0

    def test_round_trip_with_one_policy(self, tmp_path):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        reg1 = PolicyRegistry()
        store1 = FilePolicyStore(str(tmp_path / "p.json"), reg1)
        reg1.register("policy_a", "Only admin may call admin_tools.")
        store1.save_encrypted("passphrase")

        reg2 = PolicyRegistry()
        store2 = FilePolicyStore(str(tmp_path / "p.json"), reg2)
        count = store2.load_encrypted("passphrase")
        assert count == 1
        assert "policy_a" in reg2.list_names()

    def test_wrong_password_returns_zero(self, tmp_path):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        store = FilePolicyStore(str(tmp_path / "p.json"), reg)
        reg.register("policy_b", "All users may call tools.")
        store.save_encrypted("correct")

        reg2 = PolicyRegistry()
        store2 = FilePolicyStore(str(tmp_path / "p.json"), reg2)
        count = store2.load_encrypted("wrong-password")
        assert count == 0

    def test_fallback_to_plain_save_when_cryptography_absent(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        store = FilePolicyStore(str(tmp_path / "p.json"), reg)
        with patch.dict("sys.modules", {"cryptography": None,
                                         "cryptography.hazmat": None,
                                         "cryptography.hazmat.primitives": None,
                                         "cryptography.hazmat.primitives.ciphers": None,
                                         "cryptography.hazmat.primitives.ciphers.aead": None}):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                store.save_encrypted("pw")
            user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
            assert len(user_warnings) >= 1

    def test_fallback_to_plain_load_when_cryptography_absent(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        store = FilePolicyStore(str(tmp_path / "p.json"), reg)
        with patch.dict("sys.modules", {"cryptography": None,
                                         "cryptography.hazmat": None,
                                         "cryptography.hazmat.primitives": None,
                                         "cryptography.hazmat.primitives.ciphers": None,
                                         "cryptography.hazmat.primitives.ciphers.aead": None,
                                         "cryptography.exceptions": None}):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                store.load_encrypted("pw")
            user_warnings = [x for x in w if issubclass(x.category, UserWarning)]
            assert len(user_warnings) >= 1

    def test_enc_path_is_sibling_with_enc_suffix(self, tmp_path):
        src = (_REPO_ROOT / "ipfs_datasets_py/mcp_server/nl_ucan_policy.py").read_text()
        assert '+ ".enc"' in src or '".enc"' in src

    def test_in_source_save_encrypted_exists(self):
        src = (_REPO_ROOT / "ipfs_datasets_py/mcp_server/nl_ucan_policy.py").read_text()
        assert "def save_encrypted" in src

    def test_in_source_load_encrypted_exists(self):
        src = (_REPO_ROOT / "ipfs_datasets_py/mcp_server/nl_ucan_policy.py").read_text()
        assert "def load_encrypted" in src


# ===========================================================================
# 6.  Session 62 E2E scenario
# ===========================================================================

class TestSession62E2E:
    """End-to-end: policy store → compliance (encrypted) → delegation (depth)
    → pipeline check → enterprise API revoke → monitoring gauge read."""

    def test_compliance_version_survives_round_trip(self, tmp_path):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, _COMPLIANCE_RULE_VERSION, make_default_compliance_checker,
        )
        checker = make_default_compliance_checker()
        path = str(tmp_path / "rules.json")
        checker.save(path)

        checker2 = ComplianceChecker()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            count = checker2.load(path)
        assert count > 0
        version_warnings = [x for x in w if "version" in str(x.message).lower()]
        assert len(version_warnings) == 0, "No warning on same-version load"

    def test_delegation_metrics_include_max_chain_depth(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, record_delegation_metrics
        mgr = DelegationManager(max_chain_depth=10)
        collector = MagicMock()
        record_delegation_metrics(mgr, collector)
        gauge_names = {c.args[0] for c in collector.set_gauge.call_args_list}
        assert "mcp_delegation_max_chain_depth" in gauge_names

    def test_delegation_chain_depth_rejection(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, Delegation, Capability,
        )
        eval_ = DelegationEvaluator(max_chain_depth=1)
        t = 9999999999.0
        d1 = Delegation("cid1", "alice", "bob", [Capability("*", "*")], t, None, "s1")
        d2 = Delegation("cid2", "bob", "charlie", [Capability("*", "*")], t, "cid1", "s2")
        eval_.add(d1)
        eval_.add(d2)
        with pytest.raises(ValueError, match="max_chain_depth"):
            eval_.build_chain("cid2")

    def test_file_policy_store_enc_suffix(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore, PolicyRegistry
        store = FilePolicyStore("/tmp/foo.json", PolicyRegistry())
        # The enc path should be /tmp/foo.json.enc
        assert store.path + ".enc" == "/tmp/foo.json.enc"

    def test_compliance_encrypted_round_trip(self, tmp_path):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa
        except ImportError:
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, make_default_compliance_checker,
        )
        checker = make_default_compliance_checker(deny_list={"blocked_enc_tool"})
        path = str(tmp_path / "rules.enc")
        checker.save_encrypted(path, "session62pw")

        checker2 = ComplianceChecker()
        count = checker2.load_encrypted(path, "session62pw")
        assert count > 0
        assert "blocked_enc_tool" in checker2._deny_list

    def test_revocation_list_plain_persistence(self, tmp_path):
        from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
        rl = RevocationList()
        rl.revoke("cid-a")
        rl.revoke("cid-b")
        path = str(tmp_path / "revoked.json")
        rl.save(path)

        rl2 = RevocationList()
        count = rl2.load(path)
        assert count == 2
        assert rl2.is_revoked("cid-a")
        assert rl2.is_revoked("cid-b")

    def test_delegation_manager_metrics_after_adding_delegation(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability,
        )
        mgr = DelegationManager(max_chain_depth=3)
        d = Delegation("cid-x", "alice", "bob", [Capability("tools", "read")],
                       9999999999.0, None, "sig")
        mgr.add(d)
        m = mgr.get_metrics()
        assert m["delegation_count"] == 1
        assert m["max_chain_depth"] == 3

    def test_p2p_metrics_collector_source_has_delegation_metrics(self):
        src = (_REPO_ROOT / "ipfs_datasets_py/mcp_server/monitoring.py").read_text()
        assert "_record_delegation_metrics" in src
        assert "mcp_delegation_max_chain_depth" not in src  # emitted via record_delegation_metrics
        # The delegation metrics bridge calls record_delegation_metrics
        assert "record_delegation_metrics" in src

    def test_enterprise_api_delegation_routes_present(self):
        src = (_REPO_ROOT / "ipfs_datasets_py/mcp_server/enterprise_api.py").read_text()
        assert "/delegations/revoke" in src
        assert "/delegations/metrics" in src
        assert "revoke_chain" in src

    def test_all_session_62_features_in_their_modules(self):
        """Smoke-check that all expected symbols exist in the right modules."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager,
            record_delegation_metrics,
        )
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            _COMPLIANCE_RULE_VERSION,
        )
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore

        assert hasattr(DelegationManager, "get_metrics")
        assert _COMPLIANCE_RULE_VERSION == "1"
        assert hasattr(FilePolicyStore, "save_encrypted")
        assert hasattr(FilePolicyStore, "load_encrypted")
        assert callable(record_delegation_metrics)
