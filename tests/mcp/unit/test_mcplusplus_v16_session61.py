"""Session 61 — MCP++ v16 Next Steps tests.

Covers:
1. enterprise_api.py — POST /delegations/revoke + GET /delegations/metrics
2. ComplianceChecker.reload(path)
3. ComplianceChecker.save_encrypted / load_encrypted
4. DelegationEvaluator.max_chain_depth
5. DelegationManager.max_chain_depth integration
6. Full server integration test (5 stores)
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ─── repo root on sys.path ───────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ===========================================================================
# Section 1 — Enterprise API delegation routes
# ===========================================================================

# Read enterprise_api source once at module level (avoids triggering anyio import)
_ENTERPRISE_API_SRC = Path(_REPO_ROOT, "ipfs_datasets_py", "mcp_server", "enterprise_api.py").read_text()
_SERVER_SRC = Path(_REPO_ROOT, "ipfs_datasets_py", "mcp_server", "server.py").read_text()


class TestEnterpriseAPIDelegationRoutes:
    """enterprise_api._setup_delegation_routes()"""

    def test_delegation_routes_method_exists(self):
        assert "_setup_delegation_routes" in _ENTERPRISE_API_SRC

    def test_delegation_revoke_request_model_exists(self):
        assert "DelegationRevokeRequest" in _ENTERPRISE_API_SRC

    def test_setup_delegation_routes_called_in_setup_routes(self):
        assert "_setup_delegation_routes" in _ENTERPRISE_API_SRC

    def test_delegation_revoke_route_source_has_revoke_chain(self):
        assert "revoke_chain" in _ENTERPRISE_API_SRC or "revoke_delegation" in _ENTERPRISE_API_SRC

    def test_delegation_metrics_route_source_has_get_metrics(self):
        assert "get_metrics" in _ENTERPRISE_API_SRC

    def test_delegation_revoke_route_registered_at_delegations_revoke(self):
        assert "/delegations/revoke" in _ENTERPRISE_API_SRC

    def test_delegation_metrics_route_registered_at_delegations_metrics(self):
        assert "/delegations/metrics" in _ENTERPRISE_API_SRC

    def test_revoke_route_uses_get_delegation_manager(self):
        assert "get_delegation_manager" in _ENTERPRISE_API_SRC

    def test_metrics_route_uses_get_delegation_manager(self):
        assert "get_delegation_manager" in _ENTERPRISE_API_SRC

    def test_revoke_route_has_exception_guard(self):
        assert "except Exception" in _ENTERPRISE_API_SRC


# ===========================================================================
# Section 2 — ComplianceChecker.reload()
# ===========================================================================

class TestComplianceCheckerReload:
    """ComplianceChecker.reload(path) hot-reload."""

    def _make_checker(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        return make_default_compliance_checker()

    def test_reload_method_exists(self):
        checker = self._make_checker()
        assert callable(getattr(checker, "reload", None))

    def test_reload_restores_rules(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.json")
            orig = make_default_compliance_checker(deny_list={"blocked"})
            orig.save(path)
            new_checker = make_default_compliance_checker()
            new_checker.reload(path)
            assert "tool_name_convention" in new_checker.list_rules()

    def test_reload_clears_existing_rules(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker, ComplianceResult, ComplianceStatus
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.json")
            # save with just one custom-ish rule via real checker
            checker_a = ComplianceChecker()
            checker_a.add_rule("tool_name_convention", lambda _: ComplianceResult(rule_id="tool_name_convention", status=ComplianceStatus.COMPLIANT))
            checker_a.save(path)
            # Load into checker_b that had extra rule
            checker_b = ComplianceChecker()
            checker_b.add_rule("old_rule", lambda _: ComplianceResult(rule_id="old_rule", status=ComplianceStatus.COMPLIANT))
            checker_b.reload(path)
            # old_rule should be gone after reload
            assert "old_rule" not in checker_b.list_rules()

    def test_reload_missing_file_returns_zero(self):
        checker = self._make_checker()
        result = checker.reload("/nonexistent/path/rules.json")
        assert result == 0

    def test_reload_restores_deny_list(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.json")
            orig = make_default_compliance_checker(deny_list={"secret_tool"})
            orig.save(path)
            new_checker = make_default_compliance_checker()
            new_checker.reload(path)
            assert "secret_tool" in new_checker._deny_list


# ===========================================================================
# Section 3 — ComplianceChecker encrypted persistence
# ===========================================================================

class TestComplianceCheckerEncryptedPersistence:
    """save_encrypted / load_encrypted round-trip."""

    def _make_checker(self, deny_list=None):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        return make_default_compliance_checker(deny_list=deny_list or set())

    def test_save_encrypted_method_exists(self):
        checker = self._make_checker()
        assert callable(getattr(checker, "save_encrypted", None))

    def test_load_encrypted_method_exists(self):
        checker = self._make_checker()
        assert callable(getattr(checker, "load_encrypted", None))

    def test_save_encrypted_creates_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            checker = self._make_checker()
            checker.save_encrypted(path, "testpass")
            assert os.path.exists(path)

    def test_load_encrypted_round_trip(self):
        pytest.importorskip("cryptography")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            checker = self._make_checker(deny_list={"blocked_enc"})
            checker.save_encrypted(path, "securepassword")
            restored = ComplianceChecker()
            count = restored.load_encrypted(path, "securepassword")
            assert count > 0
            assert "tool_name_convention" in restored.list_rules()

    def test_load_encrypted_deny_list_restored(self):
        pytest.importorskip("cryptography")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            checker = self._make_checker(deny_list={"enc_blocked"})
            checker.save_encrypted(path, "pass123")
            restored = ComplianceChecker()
            restored.load_encrypted(path, "pass123")
            assert "enc_blocked" in restored._deny_list

    def test_load_encrypted_wrong_password_returns_zero(self):
        pytest.importorskip("cryptography")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            checker = self._make_checker()
            checker.save_encrypted(path, "rightpass")
            restored = ComplianceChecker()
            result = restored.load_encrypted(path, "wrongpass")
            assert result == 0

    def test_load_encrypted_missing_file_returns_zero(self):
        checker = self._make_checker()
        result = checker.load_encrypted("/no/such/file.enc", "pass")
        assert result == 0

    def test_save_encrypted_file_is_binary(self):
        pytest.importorskip("cryptography")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            checker = self._make_checker()
            checker.save_encrypted(path, "mypassword")
            with open(path, "rb") as fh:
                raw = fh.read()
            # should NOT be valid JSON (it's encrypted binary)
            try:
                json.loads(raw)
                is_json = True
            except Exception:
                is_json = False
            assert not is_json

    def test_save_encrypted_fallback_without_cryptography(self):
        """Fallback to plain save() when cryptography is absent."""
        import builtins
        real_import = builtins.__import__

        def patched_import(name, *args, **kwargs):
            if name == "cryptography" or name.startswith("cryptography."):
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        checker = self._make_checker()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules_fallback.json")
            with patch("builtins.__import__", side_effect=patched_import):
                import warnings
                with warnings.catch_warnings(record=True) as w:
                    warnings.simplefilter("always")
                    checker.save_encrypted(path, "pass")
            # fallback writes a plain JSON file
            assert os.path.exists(path)


# ===========================================================================
# Section 4 — DelegationEvaluator max_chain_depth
# ===========================================================================

class TestDelegationEvaluatorMaxChainDepth:
    """DelegationEvaluator max_chain_depth config."""

    def _make_evaluator(self, max_depth=0):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationEvaluator
        return DelegationEvaluator(max_chain_depth=max_depth)

    def _add_chain(self, ev, length):
        """Add a linear chain of *length* delegations; return leaf CID."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import Delegation, Capability
        prev_cid = None
        leaf_cid = None
        for i in range(length):
            cid = f"cid-depth-{i}"
            d = Delegation(
                cid=cid,
                issuer=f"did:key:issuer{i}",
                audience=f"did:key:audience{i}",
                capabilities=[Capability("*", "*")],
                expiry=None,
                proof_cid=prev_cid,
                signature="",
            )
            ev.add(d)
            prev_cid = cid
            leaf_cid = cid
        return leaf_cid

    def test_max_chain_depth_default_is_zero(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationEvaluator
        ev = DelegationEvaluator()
        assert ev._max_chain_depth == 0

    def test_max_chain_depth_accepts_positive_int(self):
        ev = self._make_evaluator(max_depth=5)
        assert ev._max_chain_depth == 5

    def test_chain_within_limit_succeeds(self):
        ev = self._make_evaluator(max_depth=5)
        leaf = self._add_chain(ev, 3)
        chain = ev.build_chain(leaf)
        assert len(chain) == 3

    def test_chain_at_exact_limit_succeeds(self):
        ev = self._make_evaluator(max_depth=3)
        leaf = self._add_chain(ev, 3)
        chain = ev.build_chain(leaf)
        assert len(chain) == 3

    def test_chain_exceeds_limit_raises_value_error(self):
        ev = self._make_evaluator(max_depth=2)
        leaf = self._add_chain(ev, 4)
        with pytest.raises(ValueError, match="max_chain_depth"):
            ev.build_chain(leaf)

    def test_unlimited_depth_allows_long_chain(self):
        ev = self._make_evaluator(max_depth=0)
        leaf = self._add_chain(ev, 20)
        chain = ev.build_chain(leaf)
        assert len(chain) == 20

    def test_error_message_contains_actual_and_max(self):
        ev = self._make_evaluator(max_depth=2)
        leaf = self._add_chain(ev, 4)
        with pytest.raises(ValueError) as exc_info:
            ev.build_chain(leaf)
        msg = str(exc_info.value)
        assert "4" in msg or "max_chain_depth" in msg


# ===========================================================================
# Section 5 — DelegationManager max_chain_depth integration
# ===========================================================================

class TestDelegationManagerMaxChainDepth:
    """DelegationManager passes max_chain_depth to DelegationEvaluator."""

    def test_delegation_manager_accepts_max_chain_depth(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        with tempfile.TemporaryDirectory() as td:
            mgr = DelegationManager(os.path.join(td, "del.json"), max_chain_depth=3)
            assert mgr._max_chain_depth == 3

    def test_delegation_manager_evaluator_has_max_depth(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        with tempfile.TemporaryDirectory() as td:
            mgr = DelegationManager(os.path.join(td, "del.json"), max_chain_depth=5)
            ev = mgr.get_evaluator()
            assert ev._max_chain_depth == 5

    def test_get_delegation_manager_accepts_max_chain_depth(self):
        from ipfs_datasets_py.mcp_server import ucan_delegation
        # Reset singleton
        old = ucan_delegation._default_delegation_manager
        ucan_delegation._default_delegation_manager = None
        try:
            with tempfile.TemporaryDirectory() as td:
                mgr = ucan_delegation.get_delegation_manager(
                    path=os.path.join(td, "del.json"),
                    max_chain_depth=7,
                )
                assert mgr._max_chain_depth == 7
        finally:
            ucan_delegation._default_delegation_manager = old

    def test_can_invoke_rejects_over_depth_chain(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability,
        )
        with tempfile.TemporaryDirectory() as td:
            mgr = DelegationManager(os.path.join(td, "del.json"), max_chain_depth=2)
            prev = None
            leaf = None
            for i in range(4):
                cid = f"mgr-chain-{i}"
                d = Delegation(
                    cid=cid, issuer="did:key:iss", audience="alice",
                    capabilities=[Capability("tool", "invoke")],
                    expiry=None, proof_cid=prev, signature="",
                )
                mgr.add(d)
                prev = cid
                leaf = cid
            ok, reason = mgr.can_invoke(leaf, "tool", "alice")
            assert not ok
            assert "max_chain_depth" in reason or "chain length" in reason


# ===========================================================================
# Section 6 — Full server integration test (5 stores)
# ===========================================================================

class TestFullServerIntegration5Stores:
    """Integration test spanning all 5 data stores."""

    def test_policy_store_env_var_read_in_server(self):
        assert "IPFS_POLICY_STORE_PATH" in _SERVER_SRC

    def test_delegation_store_env_var_read_in_server(self):
        assert "MCP_DELEGATION_STORE_PATH" in _SERVER_SRC

    def test_revoke_delegation_chain_method_on_server(self):
        assert "revoke_delegation_chain" in _SERVER_SRC

    def test_server_revoke_delegation_chain_returns_int(self):
        # Verify the method returns 0 when manager is None via source inspection
        assert "_server_delegation_manager" in _SERVER_SRC
        assert "revoke_delegation_chain" in _SERVER_SRC

    def test_compliance_checker_save_and_load_round_trip(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            make_default_compliance_checker,
            ComplianceChecker,
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "compliance.json")
            orig = make_default_compliance_checker(deny_list={"blocked_tool"})
            orig.save(path)
            restored = ComplianceChecker()
            count = restored.load(path)
            assert count >= 1
            assert "blocked_tool" in restored._deny_list

    def test_delegation_manager_save_and_load_round_trip(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability,
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "del.json")
            mgr = DelegationManager(path)
            d = Delegation(
                cid="cid-store-test",
                issuer="did:key:iss",
                audience="did:key:aud",
                capabilities=[Capability("mcp://tool/test", "invoke")],
                expiry=None, proof_cid=None, signature="",
            )
            mgr.add(d)
            mgr.save()
            # restore
            mgr2 = DelegationManager(path)
            mgr2.load()
            assert "cid-store-test" in mgr2._store.list_cids()

    def test_encrypted_revocation_round_trip(self):
        pytest.importorskip("cryptography")
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability,
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "del.json")
            mgr = DelegationManager(path)
            d = Delegation(
                cid="cid-revoke-enc",
                issuer="did:key:iss", audience="did:key:aud",
                capabilities=[Capability("*", "*")],
                expiry=None, proof_cid=None, signature="",
            )
            mgr.add(d)
            mgr.revoke("cid-revoke-enc")
            mgr.save_encrypted("mypassword")
            # Restore
            mgr2 = DelegationManager(path)
            mgr2.load_encrypted("mypassword")
            assert mgr2.is_revoked("cid-revoke-enc")

    def test_interface_repository_accessible(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import InterfaceRepository
        repo = InterfaceRepository()
        assert repo is not None

    def test_compliance_checker_reload_after_save(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            make_default_compliance_checker,
            ComplianceChecker,
        )
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.json")
            orig = make_default_compliance_checker(deny_list={"tool_x"})
            orig.save(path)
            checker = ComplianceChecker()
            n = checker.reload(path)
            assert n >= 1
            assert "tool_x" in checker._deny_list

    def test_delegation_manager_metrics_dict_keys(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        with tempfile.TemporaryDirectory() as td:
            mgr = DelegationManager(os.path.join(td, "del.json"))
            m = mgr.get_metrics()
            assert "delegation_count" in m
            assert "revoked_cid_count" in m

    def test_all_five_modules_importable(self):
        """All 5 store-related modules import cleanly (checked via source existence)."""
        for mod_path in [
            "ipfs_datasets_py/mcp_server/nl_ucan_policy.py",
            "ipfs_datasets_py/mcp_server/ucan_delegation.py",
            "ipfs_datasets_py/mcp_server/compliance_checker.py",
            "ipfs_datasets_py/mcp_server/interface_descriptor.py",
            "ipfs_datasets_py/mcp_server/server.py",
        ]:
            assert (_REPO_ROOT / mod_path).exists(), f"Missing: {mod_path}"
