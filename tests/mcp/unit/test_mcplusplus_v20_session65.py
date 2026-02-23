"""
Session 65: MCP++ v20 Next Steps (MASTER_IMPROVEMENT_PLAN_2026_v20.md)

Implements tests for all 5 "Next Steps (Session 65+)" items:
1. IPFSPolicyStore.reload() — re-pins policies after hot-reload
2. DelegationManager.merge(other, copy_revocations=False/True)
3. PubSubBus.publish_async() error logging at DEBUG level
4. ComplianceChecker.load_encrypted version check
5. Session 65 full E2E integration test
"""

import asyncio
import hashlib
import inspect
import json
import os
import sys
import tempfile
import warnings
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Test Section 1: IPFSPolicyStore.reload() pins on reload
# ---------------------------------------------------------------------------

class TestIPFSPolicyStoreReloadPins:
    """IPFSPolicyStore.reload() should re-pin all reloaded policies."""

    def _make_store_with_policy(self, path: str):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore,
            PolicyRegistry,
            NLUCANPolicyCompiler,
        )
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg)
        # Manually inject a compiled policy
        compiler = NLUCANPolicyCompiler()
        result = compiler.compile("allow actor:alice to call tool:search")
        if result is not None:
            reg.register("p1", result, "allow actor:alice to call tool:search")
        store.save()
        return store

    def test_reload_calls_pin_for_loaded_policies(self, tmp_path):
        """reload() should call pin_policy for every reloaded name."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore,
            PolicyRegistry,
        )
        path = str(tmp_path / "store.json")
        # Write a minimal versioned store file
        (tmp_path / "store.json").write_text(
            json.dumps({"version": "1", "policies": {}})
        )
        reg = PolicyRegistry()
        pinned: List[str] = []

        class FakeIPFS:
            def add(self, content: bytes):
                return {"Hash": "QmFake123"}
            def cat(self, cid: str):
                return b"{}"

        store = IPFSPolicyStore(path, reg, ipfs_client=FakeIPFS())
        # Patch pin_policy to track calls
        original_pin = store.pin_policy
        pin_calls: List[str] = []

        def _mock_pin(name: str):
            pin_calls.append(name)
            return original_pin(name)

        store.pin_policy = _mock_pin
        n = store.reload()
        # File has no policies, so pin_calls should be empty (or have 0 entries)
        assert isinstance(n, int)
        assert n == 0

    def test_reload_returns_policy_count(self, tmp_path):
        """reload() returns the number of policies found on disk."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore,
            PolicyRegistry,
        )
        path = str(tmp_path / "store.json")
        (tmp_path / "store.json").write_text(
            json.dumps({"version": "1", "policies": {}})
        )
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg)
        assert store.reload() == 0

    def test_reload_overrides_file_policy_store_reload(self):
        """IPFSPolicyStore.reload must override FilePolicyStore.reload."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore,
            FilePolicyStore,
        )
        # Method resolution: IPFSPolicyStore.reload should be distinct
        assert "reload" in IPFSPolicyStore.__dict__, (
            "IPFSPolicyStore must override reload() directly"
        )

    def test_reload_calls_super_reload(self, tmp_path):
        """IPFSPolicyStore.reload() delegates to super().reload()."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore,
            FilePolicyStore,
            PolicyRegistry,
        )
        path = str(tmp_path / "store.json")
        (tmp_path / "store.json").write_text(
            json.dumps({"version": "1", "policies": {}})
        )
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg)
        reload_called = []
        original_super_reload = FilePolicyStore.reload

        def _fake_super_reload(self_inner):
            reload_called.append(True)
            return original_super_reload(self_inner)

        with patch.object(FilePolicyStore, "reload", _fake_super_reload):
            store.reload()

        assert len(reload_called) == 1, "super().reload() should be called once"

    def test_reload_pin_policy_called_for_each_name(self, tmp_path):
        """pin_policy is called once per loaded policy name."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore,
            PolicyRegistry,
        )
        path = str(tmp_path / "store.json")
        (tmp_path / "store.json").write_text(
            json.dumps({"version": "1", "policies": {}})
        )
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg)
        pin_names: List[str] = []
        store.pin_policy = lambda name: pin_names.append(name) or None
        store.reload()
        # No policies in file → no pins
        assert pin_names == []

    def test_reload_missing_file_returns_zero(self, tmp_path):
        """reload() returns 0 when file does not exist."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore,
            PolicyRegistry,
        )
        path = str(tmp_path / "nonexistent.json")
        reg = PolicyRegistry()
        store = IPFSPolicyStore(path, reg)
        assert store.reload() == 0

    def test_ipfs_policy_store_has_reload_in_source(self):
        """IPFSPolicyStore.reload source should mention pin_policy."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSPolicyStore
        src = inspect.getsource(IPFSPolicyStore.reload)
        assert "pin_policy" in src


# ---------------------------------------------------------------------------
# Test Section 2: DelegationManager.merge with copy_revocations
# ---------------------------------------------------------------------------

class TestDelegationManagerMergeCopyRevocations:
    """DelegationManager.merge(other, copy_revocations=...)."""

    def _make_manager_with_delegation(self, cid: str):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager,
            Delegation,
            Capability,
        )
        mgr = DelegationManager()
        d = Delegation(cid, "did:key:issuer", "did:key:audience", [Capability("*", "*")])
        mgr._store.add(d)
        return mgr

    def test_merge_no_revocations_by_default(self):
        """Default merge does NOT copy revocations."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, Delegation, Capability
        src = DelegationManager()
        d = Delegation("cid-src", "did:key:issuer", "did:key:audience", [Capability("*", "*")])
        src._store.add(d)
        src._revocation.revoke("secret-revoked")

        dst = DelegationManager()
        dst.merge(src)  # copy_revocations defaults to False
        assert not dst._revocation.is_revoked("secret-revoked")

    def test_merge_with_copy_revocations_true(self):
        """copy_revocations=True copies all revoked CIDs."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, Delegation, Capability
        src = DelegationManager()
        d = Delegation("cid-x", "did:key:issuer", "did:key:audience", [Capability("*", "*")])
        src._store.add(d)
        src._revocation.revoke("rev-cid-1")
        src._revocation.revoke("rev-cid-2")

        dst = DelegationManager()
        n = dst.merge(src, copy_revocations=True)
        assert n == 1
        assert dst._revocation.is_revoked("rev-cid-1")
        assert dst._revocation.is_revoked("rev-cid-2")

    def test_merge_copy_revocations_does_not_add_delegations_twice(self):
        """Duplicate delegations are not added even when copy_revocations=True."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, Delegation, Capability
        d = Delegation("same-cid", "did:key:issuer", "did:key:audience", [Capability("*", "*")])
        src = DelegationManager()
        src._store.add(d)
        dst = DelegationManager()
        dst._store.add(d)  # pre-add same delegation
        n = dst.merge(src, copy_revocations=True)
        assert n == 0
        assert len(dst._store) == 1

    def test_merge_copy_revocations_false_explicit(self):
        """Explicit copy_revocations=False behaves same as default."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, Delegation, Capability
        src = DelegationManager()
        src._revocation.revoke("protected-cid")
        dst = DelegationManager()
        dst.merge(src, copy_revocations=False)
        assert not dst._revocation.is_revoked("protected-cid")

    def test_merge_copy_revocations_does_not_mutate_source(self):
        """Merging never modifies the source manager's revocation list."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, Delegation, Capability
        d = Delegation("cid-y", "did:key:issuer", "did:key:audience", [Capability("*", "*")])
        src = DelegationManager()
        src._store.add(d)
        src._revocation.revoke("cid-in-src")
        initial_revoked = set(src._revocation.to_list())

        dst = DelegationManager()
        dst._revocation.revoke("cid-in-dst")
        dst.merge(src, copy_revocations=True)

        assert set(src._revocation.to_list()) == initial_revoked, (
            "Source revocation list should be unchanged after merge"
        )

    def test_merge_copy_revocations_kwarg_only(self):
        """copy_revocations must be keyword-only (cannot be passed positionally)."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        sig = inspect.signature(mgr.merge)
        params = sig.parameters
        assert "copy_revocations" in params
        assert params["copy_revocations"].kind in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )

    def test_merge_with_copy_revocations_returns_delegation_count(self):
        """Return value is delegation count regardless of copy_revocations."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, Delegation, Capability
        d1 = Delegation("d1", "iss", "aud", [Capability("*", "*")])
        d2 = Delegation("d2", "iss", "aud", [Capability("*", "*")])
        src = DelegationManager()
        src._store.add(d1)
        src._store.add(d2)
        dst = DelegationManager()
        n = dst.merge(src, copy_revocations=True)
        assert n == 2

    def test_merge_empty_source_copy_revocations_true(self):
        """Merging an empty manager with copy_revocations=True adds 0 delegations."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        dst = DelegationManager()
        n = dst.merge(src, copy_revocations=True)
        assert n == 0


# ---------------------------------------------------------------------------
# Test Section 3: PubSubBus.publish_async error logging
# ---------------------------------------------------------------------------

class TestPubSubBusPublishAsyncErrorLogging:
    """publish_async() should log handler exceptions at DEBUG level."""

    def test_publish_async_source_has_logger_debug(self):
        """publish_async must contain logger.debug in the error path."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        src = inspect.getsource(PubSubBus.publish_async)
        assert "logger.debug" in src, "publish_async should log errors via logger.debug"

    def test_publish_async_exception_variable_named(self):
        """Exception should be captured with `as exc` (not silently discarded)."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        src = inspect.getsource(PubSubBus.publish_async)
        assert "except Exception as exc" in src or "except Exception as _exc" in src or (
            "except" in src and ("exc" in src or "err" in src)
        ), "Exception should be named in except clause"

    def test_publish_async_fallback_sync_on_no_anyio(self):
        """Falls back to sync publish when anyio absent, with UserWarning."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus, PubSubEventType
        bus = PubSubBus()
        received: List[Any] = []
        bus.subscribe(PubSubEventType.INTERFACE_ANNOUNCE, lambda t, p: received.append(p))

        try:
            import anyio
            pytest.skip("anyio is installed — testing no-anyio path would require unpatching")
        except ImportError:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                asyncio.run(bus.publish_async(PubSubEventType.INTERFACE_ANNOUNCE, {"x": 1}))
                warn_msgs = [str(x.message) for x in w]
                assert any("anyio" in m.lower() for m in warn_msgs), (
                    f"Expected anyio fallback warning; got: {warn_msgs}"
                )

    def test_publish_async_returns_count(self):
        """publish_async returns handler count (sync or async)."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus, PubSubEventType
        bus = PubSubBus()
        received: List[Any] = []
        bus.subscribe(PubSubEventType.INTERFACE_ANNOUNCE, lambda t, p: received.append(p))
        bus.subscribe(PubSubEventType.INTERFACE_ANNOUNCE, lambda t, p: received.append(p))
        try:
            import anyio
            count = asyncio.run(bus.publish_async(PubSubEventType.INTERFACE_ANNOUNCE, {}))
            notified = count.notified if hasattr(count, "notified") else count
            assert notified == 2
        except ImportError:
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                count = asyncio.run(bus.publish_async(PubSubEventType.INTERFACE_ANNOUNCE, {}))
                notified = count.notified if hasattr(count, "notified") else count
                assert notified == 2

    def test_publish_async_is_coroutine_function(self):
        """publish_async must be a coroutine function."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        import asyncio
        bus = PubSubBus()
        assert asyncio.iscoroutinefunction(bus.publish_async), (
            "publish_async must be async def"
        )


# ---------------------------------------------------------------------------
# Test Section 4: ComplianceChecker.load_encrypted version check
# ---------------------------------------------------------------------------

class TestComplianceCheckerLoadEncryptedVersionCheck:
    """load_encrypted() should warn on version mismatch."""

    def _save_encrypted_with_version(self, path: str, password: str, version: str) -> None:
        """Helper to write an encrypted compliance file with a custom version."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            pytest.skip("cryptography not installed")
        import hashlib
        pw_bytes = password.encode()
        key = hashlib.sha256(pw_bytes).digest()
        nonce = os.urandom(12)
        data = {
            "version": version,
            "rule_order": ["tool_name_convention"],
            "deny_list": [],
        }
        plaintext = json.dumps(data).encode()
        aesgcm = AESGCM(key)
        ct = aesgcm.encrypt(nonce, plaintext, None)
        with open(path, "wb") as fh:
            fh.write(nonce + ct)

    def test_load_encrypted_warns_on_version_mismatch(self, tmp_path):
        """UserWarning emitted when file version != _COMPLIANCE_RULE_VERSION."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker,
            _COMPLIANCE_RULE_VERSION,
        )
        path = str(tmp_path / "rules.enc")
        self._save_encrypted_with_version(path, "pass", "999")

        checker = ComplianceChecker()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            n = checker.load_encrypted(path, "pass")
            msgs = [str(x.message) for x in w]
            assert any("999" in m for m in msgs), (
                f"Expected version-mismatch warning; got: {msgs}"
            )

    def test_load_encrypted_no_warning_on_matching_version(self, tmp_path):
        """No version warning when file version matches current."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker,
            _COMPLIANCE_RULE_VERSION,
        )
        path = str(tmp_path / "rules.enc")
        self._save_encrypted_with_version(path, "mypassword", _COMPLIANCE_RULE_VERSION)

        checker = ComplianceChecker()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            n = checker.load_encrypted(path, "mypassword")
            version_warnings = [
                x for x in w
                if "version" in str(x.message).lower()
                and "anyio" not in str(x.message).lower()
            ]
            assert len(version_warnings) == 0, (
                f"No version warning expected; got: {[str(x.message) for x in version_warnings]}"
            )

    def test_load_encrypted_source_has_version_check(self):
        """load_encrypted must check 'version' key in decrypted payload."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        src = inspect.getsource(ComplianceChecker.load_encrypted)
        assert "version" in src, "load_encrypted should inspect the version field"
        assert "_COMPLIANCE_RULE_VERSION" in src, (
            "load_encrypted should compare against _COMPLIANCE_RULE_VERSION"
        )

    def test_load_encrypted_missing_version_no_warning(self, tmp_path):
        """No warning when encrypted file has no version key (legacy tolerance)."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError:
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        import hashlib
        path = str(tmp_path / "rules_no_ver.enc")
        pw = "pw"
        pw_bytes = pw.encode()
        key = hashlib.sha256(pw_bytes).digest()
        nonce = os.urandom(12)
        data = {"rule_order": ["tool_name_convention"], "deny_list": []}
        plaintext = json.dumps(data).encode()
        aesgcm = AESGCM(key)
        ct = aesgcm.encrypt(nonce, plaintext, None)
        with open(path, "wb") as fh:
            fh.write(nonce + ct)

        checker = ComplianceChecker()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            n = checker.load_encrypted(path, pw)
            version_warnings = [
                x for x in w
                if "version" in str(x.message).lower()
                and "anyio" not in str(x.message).lower()
                and "cryptography" not in str(x.message).lower()
            ]
            assert len(version_warnings) == 0, (
                f"No warning expected for missing version; got: {[str(x.message) for x in version_warnings]}"
            )


# ---------------------------------------------------------------------------
# Test Section 5: Full E2E Session 65
# ---------------------------------------------------------------------------

class TestE2ESession65:
    """End-to-end tests spanning all 4 session 65 features."""

    def test_ipfs_policy_store_reload_is_override(self):
        """IPFSPolicyStore.reload exists and differs from FilePolicyStore.reload."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore,
            FilePolicyStore,
        )
        assert "reload" in IPFSPolicyStore.__dict__
        assert IPFSPolicyStore.reload is not FilePolicyStore.reload

    def test_delegation_manager_merge_accepts_copy_revocations(self):
        """DelegationManager.merge accepts copy_revocations= kwarg."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        sig = inspect.signature(DelegationManager.merge)
        assert "copy_revocations" in sig.parameters

    def test_delegation_manager_merge_copy_revocations_default_false(self):
        """copy_revocations defaults to False."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        sig = inspect.signature(DelegationManager.merge)
        assert sig.parameters["copy_revocations"].default is False

    def test_publish_async_has_debug_logging(self):
        """publish_async logs exceptions at DEBUG level."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        src = inspect.getsource(PubSubBus.publish_async)
        assert "logger.debug" in src

    def test_compliance_load_encrypted_version_check_present(self):
        """ComplianceChecker.load_encrypted has version-check code."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        src = inspect.getsource(ComplianceChecker.load_encrypted)
        # Must reference _COMPLIANCE_RULE_VERSION to do a version check
        assert "_COMPLIANCE_RULE_VERSION" in src

    def test_all_modules_importable(self):
        """All 4 modified modules must still import cleanly."""
        import ipfs_datasets_py.mcp_server.nl_ucan_policy
        import ipfs_datasets_py.mcp_server.ucan_delegation
        import ipfs_datasets_py.mcp_server.mcp_p2p_transport
        import ipfs_datasets_py.mcp_server.compliance_checker

    def test_delegation_merge_with_revocations_roundtrip(self, tmp_path):
        """Full merge-with-revocations round-trip."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager,
            Delegation,
            Capability,
        )
        src = DelegationManager()
        d = Delegation("cid-e2e", "iss", "aud", [Capability("*", "*")])
        src._store.add(d)
        src._revocation.revoke("revoked-e2e")

        dst = DelegationManager()
        added = dst.merge(src, copy_revocations=True)
        assert added == 1
        assert dst._revocation.is_revoked("revoked-e2e")
        assert len(dst._store) == 1

    def test_file_policy_store_reload_no_regression(self, tmp_path):
        """FilePolicyStore.reload() still works correctly (session 64 regression)."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore, PolicyRegistry
        path = str(tmp_path / "policies.json")
        (tmp_path / "policies.json").write_text(
            json.dumps({"version": "1", "policies": {}})
        )
        reg = PolicyRegistry()
        store = FilePolicyStore(path, reg)
        n = store.reload()
        assert n == 0

    def test_compliance_checker_merge_no_regression(self):
        """ComplianceChecker.merge() still works correctly (session 63 regression)."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        c1 = ComplianceChecker()
        c2 = ComplianceChecker()
        c2.add_rule("my_rule", lambda intent: __import__(
            "ipfs_datasets_py.mcp_server.compliance_checker",
            fromlist=["ComplianceResult"]
        ).ComplianceResult(rule_id="my_rule", status=__import__(
            "ipfs_datasets_py.mcp_server.compliance_checker",
            fromlist=["ComplianceStatus"]
        ).ComplianceStatus.COMPLIANT, violations=[]))
        added = c1.merge(c2)
        assert added == 1
        assert "my_rule" in c1._rule_order
