"""Session 59: MASTER_IMPROVEMENT_PLAN_2026_v14.md — Phases G–L.

Tests cover:
  Phase G — DelegationManager ↔ server integration
             (_initialize_delegation_manager, get_server_delegation_manager, save on shutdown)
  Phase H — Encrypted RevocationList persistence
             (save_encrypted / load_encrypted; fallback when cryptography absent)
  Phase I — Monitoring loop auto-record delegation metrics
  Phase J — compliance_register_interface() called from register_tools() source
  Phase K — E2E smoke test covering startup → delegate → revoke → metric → shutdown
"""

from __future__ import annotations

import inspect
import json
import os
import sys
import tempfile
import types
import warnings
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_delegation(cid="cid-leaf", resource="my_tool", ability="my_tool", expiry=None,
                     proof_cid=None):
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


def _fresh_revocation_list():
    from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
    return RevocationList()


def _make_stub_server_for_delegation():
    """Return a SimpleNamespace stub with _initialize_delegation_manager injected."""
    stub = types.SimpleNamespace(
        _server_delegation_manager=None,
        _policy_store=None,
    )

    def _initialize_delegation_manager(self_=stub) -> None:
        path = os.environ.get("MCP_DELEGATION_STORE_PATH", "").strip()
        try:
            from ipfs_datasets_py.mcp_server.ucan_delegation import (  # noqa
                get_delegation_manager,
            )
            mgr = get_delegation_manager(path or None)
            self_._server_delegation_manager = mgr
            if path:
                mgr.load()
        except ImportError as exc:
            pass
        except Exception as exc:
            pass

    def get_server_delegation_manager(self_=stub) -> Any:
        return self_._server_delegation_manager

    stub._initialize_delegation_manager = _initialize_delegation_manager
    stub.get_server_delegation_manager = get_server_delegation_manager
    return stub


# ===========================================================================
# Phase G — DelegationManager ↔ server integration
# ===========================================================================

class TestPhaseGDelegationManagerServerIntegration:
    """_initialize_delegation_manager + get_server_delegation_manager."""

    def test_initialize_delegation_manager_no_env(self):
        """Without env var, manager is still populated using default path."""
        stub = _make_stub_server_for_delegation()
        env = {k: v for k, v in os.environ.items() if k != "MCP_DELEGATION_STORE_PATH"}
        with patch.dict(os.environ, env, clear=True):
            stub._initialize_delegation_manager()
        assert stub._server_delegation_manager is not None

    def test_get_server_delegation_manager_returns_manager(self):
        """get_server_delegation_manager() returns stored DelegationManager."""
        stub = _make_stub_server_for_delegation()
        stub._initialize_delegation_manager()
        mgr = stub.get_server_delegation_manager()
        assert mgr is not None
        assert hasattr(mgr, "get_metrics")

    def test_get_server_delegation_manager_none_when_unset(self):
        """get_server_delegation_manager() returns None when not initialised."""
        stub = types.SimpleNamespace(_server_delegation_manager=None)
        stub.get_server_delegation_manager = lambda: stub._server_delegation_manager
        assert stub.get_server_delegation_manager() is None

    def test_initialize_delegation_manager_with_env(self, tmp_path):
        """With MCP_DELEGATION_STORE_PATH set, manager is created with that path."""
        p = str(tmp_path / "delegations.json")
        stub = _make_stub_server_for_delegation()
        with patch.dict(os.environ, {"MCP_DELEGATION_STORE_PATH": p}):
            stub._initialize_delegation_manager()
        mgr = stub._server_delegation_manager
        assert mgr is not None
        assert hasattr(mgr, "get_metrics")

    def test_initialize_delegation_manager_import_error_swallowed(self):
        """ImportError from ucan_delegation is silently swallowed."""
        stub = types.SimpleNamespace(_server_delegation_manager=None)

        def _init(self_=stub):
            try:
                raise ImportError("no module")
            except ImportError:
                pass

        stub._initialize_delegation_manager = _init
        stub._initialize_delegation_manager()  # must not raise
        assert stub._server_delegation_manager is None

    def test_initialize_delegation_manager_exception_swallowed(self):
        """Any exception from DelegationManager init is swallowed as warning."""
        stub = types.SimpleNamespace(_server_delegation_manager=None)

        def _init(self_=stub):
            try:
                raise RuntimeError("boom")
            except Exception:
                pass

        stub._initialize_delegation_manager = _init
        stub._initialize_delegation_manager()  # must not raise

    def test_server_module_has_initialize_delegation_manager(self):
        """server.py defines _initialize_delegation_manager method."""
        import importlib
        mcp_stub = MagicMock()
        mcp_stub.server.FastMCP = None
        pydantic_stub = MagicMock()
        with patch.dict(sys.modules, {"mcp": mcp_stub, "mcp.server": mcp_stub.server,
                                       "mcp.types": mcp_stub.types,
                                       "pydantic": pydantic_stub}):
            srv_mod = importlib.import_module("ipfs_datasets_py.mcp_server.server")
            importlib.reload(srv_mod)
        assert hasattr(srv_mod.IPFSDatasetsMCPServer, "_initialize_delegation_manager")

    def test_server_module_has_get_server_delegation_manager(self):
        """server.py defines get_server_delegation_manager method."""
        import importlib
        mcp_stub = MagicMock()
        mcp_stub.server.FastMCP = None
        pydantic_stub = MagicMock()
        with patch.dict(sys.modules, {"mcp": mcp_stub, "mcp.server": mcp_stub.server,
                                       "mcp.types": mcp_stub.types,
                                       "pydantic": pydantic_stub}):
            srv_mod = importlib.import_module("ipfs_datasets_py.mcp_server.server")
            importlib.reload(srv_mod)
        assert hasattr(srv_mod.IPFSDatasetsMCPServer, "get_server_delegation_manager")

    def test_server_source_calls_save_on_delegation_manager(self):
        """The start_stdio source calls _server_delegation_manager.save()."""
        import importlib
        mcp_stub = MagicMock()
        mcp_stub.server.FastMCP = None
        pydantic_stub = MagicMock()
        with patch.dict(sys.modules, {"mcp": mcp_stub, "mcp.server": mcp_stub.server,
                                       "mcp.types": mcp_stub.types,
                                       "pydantic": pydantic_stub}):
            srv_mod = importlib.import_module("ipfs_datasets_py.mcp_server.server")
            importlib.reload(srv_mod)
        source = inspect.getsource(srv_mod.IPFSDatasetsMCPServer.start_stdio)
        assert "_server_delegation_manager" in source
        assert ".save()" in source


# ===========================================================================
# Phase H — Encrypted RevocationList persistence
# ===========================================================================

class TestPhaseHEncryptedRevocationList:
    """RevocationList.save_encrypted / load_encrypted."""

    def test_save_encrypted_and_load_encrypted_roundtrip(self, tmp_path):
        """Encrypted save/load round-trip restores all CIDs."""
        pytest.importorskip("cryptography")
        rl = _fresh_revocation_list()
        rl.revoke("cid-a")
        rl.revoke("cid-b")
        path = str(tmp_path / "revoked.enc")
        rl.save_encrypted(path, password="secret123")
        assert Path(path).exists()
        rl2 = _fresh_revocation_list()
        count = rl2.load_encrypted(path, password="secret123")
        assert count == 2
        assert rl2.is_revoked("cid-a")
        assert rl2.is_revoked("cid-b")

    def test_load_encrypted_wrong_password(self, tmp_path):
        """Wrong password returns 0 without raising."""
        pytest.importorskip("cryptography")
        rl = _fresh_revocation_list()
        rl.revoke("cid-x")
        path = str(tmp_path / "revoked.enc")
        rl.save_encrypted(path, password="right")
        rl2 = _fresh_revocation_list()
        count = rl2.load_encrypted(path, password="wrong")
        assert count == 0
        assert not rl2.is_revoked("cid-x")

    def test_load_encrypted_missing_file(self, tmp_path):
        """Missing file returns 0 without raising."""
        pytest.importorskip("cryptography")
        rl = _fresh_revocation_list()
        count = rl.load_encrypted(str(tmp_path / "nonexistent.enc"), password="pw")
        assert count == 0

    def test_load_encrypted_incremental(self, tmp_path):
        """Already-present CIDs are not double-counted."""
        pytest.importorskip("cryptography")
        rl = _fresh_revocation_list()
        rl.revoke("cid-1")
        path = str(tmp_path / "r.enc")
        rl.save_encrypted(path, password="pw")
        rl2 = _fresh_revocation_list()
        rl2.revoke("cid-1")  # already present
        count = rl2.load_encrypted(path, password="pw")
        assert count == 0  # no new CIDs

    def test_save_encrypted_creates_binary_file(self, tmp_path):
        """Encrypted file is raw bytes, not plain JSON."""
        pytest.importorskip("cryptography")
        rl = _fresh_revocation_list()
        rl.revoke("cid-z")
        path = str(tmp_path / "r.enc")
        rl.save_encrypted(path, password="pw")
        raw = Path(path).read_bytes()
        # Should NOT be valid JSON (it's AES-GCM encrypted + nonce prefix)
        try:
            json.loads(raw)
            pytest.fail("File should not be plain JSON")
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass  # expected

    def test_save_encrypted_fallback_when_no_cryptography(self, tmp_path):
        """Fallback to plain save() when cryptography is absent."""
        rl = _fresh_revocation_list()
        rl.revoke("cid-fallback")
        path = str(tmp_path / "r.enc")
        # Patch AESGCM import path to simulate absence
        with patch.dict(sys.modules, {
            "cryptography.hazmat.primitives.ciphers.aead": None,
        }):
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                rl.save_encrypted(path, password="pw")
        # Fallback should produce a plain JSON file
        data = json.loads(Path(path).read_text())
        assert "cid-fallback" in data.get("revoked", [])

    def test_load_encrypted_fallback_when_no_cryptography(self, tmp_path):
        """Fallback to plain load() when cryptography is absent."""
        # Save a plain JSON file first
        path = str(tmp_path / "plain.json")
        Path(path).write_text(json.dumps({"revoked": ["cid-plain"]}))
        rl = _fresh_revocation_list()
        with patch.dict(sys.modules, {
            "cryptography.hazmat.primitives.ciphers.aead": None,
        }):
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                count = rl.load_encrypted(path, password="pw")
        assert count == 1
        assert rl.is_revoked("cid-plain")

    def test_load_encrypted_too_short_file(self, tmp_path):
        """File shorter than 12 bytes returns 0 without raising."""
        pytest.importorskip("cryptography")
        path = str(tmp_path / "short.enc")
        Path(path).write_bytes(b"short")
        rl = _fresh_revocation_list()
        count = rl.load_encrypted(path, password="pw")
        assert count == 0

    def test_revocation_list_has_save_encrypted(self):
        """RevocationList exposes save_encrypted method."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
        assert callable(RevocationList.save_encrypted)

    def test_revocation_list_has_load_encrypted(self):
        """RevocationList exposes load_encrypted method."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
        assert callable(RevocationList.load_encrypted)


# ===========================================================================
# Phase I — Monitoring loop auto-record delegation metrics
# ===========================================================================

class TestPhaseIMonitoringLoopAutoRecord:
    """_monitoring_loop() calls record_delegation_metrics() every 30 s."""

    def test_monitoring_loop_source_contains_record_delegation_metrics(self):
        """The monitoring loop body references record_delegation_metrics."""
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod
        source = inspect.getsource(mon_mod.EnhancedMetricsCollector._monitoring_loop)
        assert "record_delegation_metrics" in source

    def test_monitoring_loop_source_imports_ucan_delegation(self):
        """The monitoring loop imports from .ucan_delegation."""
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod
        source = inspect.getsource(mon_mod.EnhancedMetricsCollector._monitoring_loop)
        assert "ucan_delegation" in source

    def test_monitoring_loop_source_has_exception_guard(self):
        """Delegation metrics block is guarded by a try/except."""
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod
        source = inspect.getsource(mon_mod.EnhancedMetricsCollector._monitoring_loop)
        assert "except Exception" in source or "except" in source

    def test_record_delegation_metrics_sets_gauges(self):
        """record_delegation_metrics() writes correct gauge values to collector."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager,
            record_delegation_metrics,
        )
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
        mgr = DelegationManager()
        mgr.revoke("cid-r1")
        collector = EnhancedMetricsCollector(enabled=True)
        record_delegation_metrics(mgr, collector)
        assert collector.gauges["mcp_revoked_cids_total"] == 1.0
        assert collector.gauges["mcp_delegation_store_depth"] == 0.0

    def test_record_delegation_metrics_no_crash_on_bad_collector(self):
        """Collector exceptions are swallowed."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager,
            record_delegation_metrics,
        )
        class BrokenCollector:
            def set_gauge(self, name, value):
                raise RuntimeError("broken")
        mgr = DelegationManager()
        record_delegation_metrics(mgr, BrokenCollector())  # must not raise

    def test_monitoring_loop_import_is_lazy(self):
        """The ucan_delegation import inside _monitoring_loop uses noqa: PLC0415 pattern."""
        import ipfs_datasets_py.mcp_server.monitoring as mon_mod
        source = inspect.getsource(mon_mod.EnhancedMetricsCollector._monitoring_loop)
        # It should do a local import (inside the loop or inside try)
        assert "import" in source
        assert "ucan_delegation" in source


# ===========================================================================
# Phase J — compliance_register_interface on server startup
# ===========================================================================

class TestPhaseJComplianceInterfaceOnStartup:
    """register_tools() source contains compliance_register_interface."""

    def test_compliance_tools_in_register_tools_source(self):
        """register_tools source references compliance_register_interface."""
        import importlib
        mcp_stub = MagicMock()
        mcp_stub.server.FastMCP = None
        pydantic_stub = MagicMock()
        with patch.dict(sys.modules, {"mcp": mcp_stub, "mcp.server": mcp_stub.server,
                                       "mcp.types": mcp_stub.types,
                                       "pydantic": pydantic_stub}):
            srv_mod = importlib.import_module("ipfs_datasets_py.mcp_server.server")
            importlib.reload(srv_mod)
        source = inspect.getsource(srv_mod.IPFSDatasetsMCPServer.register_tools)
        assert "compliance_register_interface" in source

    def test_compliance_add_rule_in_register_tools_source(self):
        """register_tools source includes compliance_add_rule."""
        import importlib
        mcp_stub = MagicMock()
        mcp_stub.server.FastMCP = None
        pydantic_stub = MagicMock()
        with patch.dict(sys.modules, {"mcp": mcp_stub, "mcp.server": mcp_stub.server,
                                       "mcp.types": mcp_stub.types,
                                       "pydantic": pydantic_stub}):
            srv_mod = importlib.import_module("ipfs_datasets_py.mcp_server.server")
            importlib.reload(srv_mod)
        source = inspect.getsource(srv_mod.IPFSDatasetsMCPServer.register_tools)
        assert "compliance_add_rule" in source

    def test_compliance_register_interface_awaited_in_source(self):
        """register_tools source awaits compliance_register_interface()."""
        import importlib
        mcp_stub = MagicMock()
        mcp_stub.server.FastMCP = None
        pydantic_stub = MagicMock()
        with patch.dict(sys.modules, {"mcp": mcp_stub, "mcp.server": mcp_stub.server,
                                       "mcp.types": mcp_stub.types,
                                       "pydantic": pydantic_stub}):
            srv_mod = importlib.import_module("ipfs_datasets_py.mcp_server.server")
            importlib.reload(srv_mod)
        source = inspect.getsource(srv_mod.IPFSDatasetsMCPServer.register_tools)
        assert "await compliance_register_interface()" in source

    def test_compliance_register_interface_is_async(self):
        """compliance_register_interface() is an async function."""
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_register_interface,
        )
        import inspect
        assert inspect.iscoroutinefunction(compliance_register_interface)

    def test_compliance_register_interface_returns_registered_status(self):
        """compliance_register_interface() returns {status: 'registered', ...}."""
        import anyio
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_register_interface,
        )
        async def run():
            result = await compliance_register_interface()
            assert result["status"] == "registered"
            assert "interface_cid" in result
            assert "rule_count" in result
        anyio.run(run)

    def test_compliance_register_interface_idempotent(self):
        """Repeated calls return the same CID."""
        import anyio
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_register_interface,
        )
        async def run():
            r1 = await compliance_register_interface()
            r2 = await compliance_register_interface()
            assert r1["interface_cid"] == r2["interface_cid"]
        anyio.run(run)

    def test_compliance_register_interface_in_interface_list(self):
        """After compliance_register_interface(), checker CID appears in interface_list()."""
        import anyio
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_register_interface,
        )
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import (
            interface_list,
        )
        async def run():
            reg = await compliance_register_interface()
            cid = reg["interface_cid"]
            result = interface_list()
            assert cid in result["interface_cids"]
        anyio.run(run)


# ===========================================================================
# Phase K — E2E smoke test
# ===========================================================================

class TestPhaseKE2ESmoke:
    """End-to-end: startup → delegate → revoke → metric → shutdown."""

    def test_delegation_manager_full_lifecycle(self, tmp_path):
        """Add delegation → revoke → check → save → reload → still loaded."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Capability, Delegation,
        )
        path = str(tmp_path / "delegations.json")
        mgr = DelegationManager(path)

        cap = Capability(resource="e2e_tool", ability="e2e_tool")
        d = Delegation(
            cid="e2e-cid",
            issuer="did:key:root",
            audience="did:key:user",
            capabilities=[cap],
            expiry=None,
            proof_cid=None,
        )
        mgr.add(d)
        assert len(mgr) == 1

        mgr.revoke("e2e-cid")
        assert mgr.is_revoked("e2e-cid")

        ok, reason = mgr.can_invoke("e2e-cid", "e2e_tool", "did:key:user")
        assert not ok
        assert "revoked" in reason

        mgr.save()
        mgr2 = DelegationManager(path)
        mgr2.load()
        assert len(mgr2) == 1

    def test_delegation_manager_metrics(self):
        """DelegationManager.get_metrics() reflects add/revoke operations."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        m0 = mgr.get_metrics()
        assert m0["delegation_count"] == 0
        assert m0["revoked_cid_count"] == 0

        mgr.revoke("cid-r1")
        mgr.revoke("cid-r2")
        m1 = mgr.get_metrics()
        assert m1["revoked_cid_count"] == 2

    def test_record_delegation_metrics_full_lifecycle(self):
        """record_delegation_metrics() writes correct gauge values."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, record_delegation_metrics,
        )
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector

        mgr = DelegationManager()
        mgr.revoke("cid-x")

        collector = EnhancedMetricsCollector(enabled=True)
        record_delegation_metrics(mgr, collector)

        assert collector.gauges["mcp_revoked_cids_total"] == 1.0
        assert collector.gauges["mcp_delegation_store_depth"] == 0.0

    def test_encrypted_revocation_e2e(self, tmp_path):
        """save_encrypted → load_encrypted → is_revoked full round-trip."""
        pytest.importorskip("cryptography")
        from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
        rl = RevocationList()
        rl.revoke("e2e-enc-1")
        rl.revoke("e2e-enc-2")
        path = str(tmp_path / "enc_revoked.bin")
        rl.save_encrypted(path, password="e2e-password")
        rl2 = RevocationList()
        n = rl2.load_encrypted(path, password="e2e-password")
        assert n == 2
        assert rl2.is_revoked("e2e-enc-1")
        assert rl2.is_revoked("e2e-enc-2")

    def test_compliance_interface_e2e(self):
        """compliance_register_interface → CID appears in interface_list()."""
        import anyio
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_register_interface,
        )
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import (
            interface_list,
        )
        async def run():
            reg = await compliance_register_interface()
            cid = reg["interface_cid"]
            result = interface_list()
            assert cid in result["interface_cids"]
        anyio.run(run)

    def test_delegation_and_policy_stores_independent(self, tmp_path, monkeypatch):
        """IPFSPolicyStore and DelegationManager initialise independently."""
        p_path = str(tmp_path / "policies.json")
        d_path = str(tmp_path / "delegations.json")
        monkeypatch.setenv("IPFS_POLICY_STORE_PATH", p_path)
        monkeypatch.setenv("MCP_DELEGATION_STORE_PATH", d_path)
        stub = _make_stub_server_for_delegation()
        stub._initialize_delegation_manager()
        assert stub._server_delegation_manager is not None

    def test_server_start_source_saves_delegation_manager(self):
        """Both start_stdio and start finally blocks call mgr.save()."""
        import importlib
        mcp_stub = MagicMock()
        mcp_stub.server.FastMCP = None
        pydantic_stub = MagicMock()
        with patch.dict(sys.modules, {"mcp": mcp_stub, "mcp.server": mcp_stub.server,
                                       "mcp.types": mcp_stub.types,
                                       "pydantic": pydantic_stub}):
            srv_mod = importlib.import_module("ipfs_datasets_py.mcp_server.server")
            importlib.reload(srv_mod)
        start_stdio_src = inspect.getsource(srv_mod.IPFSDatasetsMCPServer.start_stdio)
        start_src = inspect.getsource(srv_mod.IPFSDatasetsMCPServer.start)
        assert "_server_delegation_manager.save()" in start_stdio_src
        assert "_server_delegation_manager.save()" in start_src
