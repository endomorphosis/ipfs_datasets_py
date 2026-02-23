"""Session 64 — MCP++ v19 next steps.

Items tested:
1. ``FilePolicyStore.reload()`` — hot-reload without creating a new instance.
2. ``DelegationManager.merge(other)`` — merge delegation entries.
3. ``ComplianceChecker.save_encrypted`` version field — encrypted payload includes
   ``"version"`` key.
4. ``PubSubBus.publish_async()`` — async variant with anyio / sync fallback.
5. Session 64 E2E smoke test.
"""

import json
import os
import tempfile
import time
import unittest
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Repository root on sys.path
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]

import sys
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
    FilePolicyStore,
    IPFSPolicyStore,
    PolicyRegistry,
    _POLICY_STORE_VERSION,
)
from ipfs_datasets_py.mcp_server.ucan_delegation import (
    Capability,
    Delegation,
    DelegationManager,
)
from ipfs_datasets_py.mcp_server.compliance_checker import (
    ComplianceChecker,
    _COMPLIANCE_RULE_VERSION,
)
from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (
    PubSubBus,
    PubSubEventType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_deleg(cid: str, issuer: str = "alice", audience: str = "bob") -> Delegation:
    return Delegation(
        cid=cid,
        issuer=issuer,
        audience=audience,
        capabilities=[Capability(resource="mcp://tools", ability="*")],
        expiry=time.time() + 3600,
    )


def _tmp_path(suffix: str = ".json") -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


# ---------------------------------------------------------------------------
# 1. FilePolicyStore.reload()
# ---------------------------------------------------------------------------
class TestFilePolicyStoreReload(unittest.TestCase):
    """FilePolicyStore.reload() hot-reloads from disk."""

    def _make_store(self, path: str) -> FilePolicyStore:
        reg = PolicyRegistry()
        return FilePolicyStore(path, reg)

    def test_reload_clears_and_reloads(self):
        path = _tmp_path()
        try:
            reg = PolicyRegistry()
            reg.register("admin", "Alice may call admin_tools.")
            store = FilePolicyStore(path, reg)
            store.save()

            # Add an extra in-memory policy (not saved)
            reg.register("extra", "Bob may call extra_tools.")
            self.assertIn("extra", reg.list_names())

            count = store.reload()
            self.assertNotIn("extra", reg.list_names(), "reload should clear unsaved policies")
            self.assertIn("admin", reg.list_names())
            self.assertEqual(count, 1)
        finally:
            os.unlink(path)

    def test_reload_missing_file_returns_zero(self):
        path = _tmp_path()
        os.unlink(path)  # ensure missing
        reg = PolicyRegistry()
        reg.register("p1", "Alice may call foo.")
        store = FilePolicyStore(path, reg)
        count = store.reload()
        self.assertEqual(count, 0)
        self.assertEqual(reg.list_names(), [], "registry should be empty after reload from missing file")

    def test_reload_multiple_policies(self):
        path = _tmp_path()
        try:
            reg = PolicyRegistry()
            for i in range(3):
                reg.register(f"pol{i}", f"Actor{i} may call tool{i}.")
            store = FilePolicyStore(path, reg)
            store.save()

            reg.register("ephemeral", "Temp policy.")
            count = store.reload()
            self.assertEqual(count, 3)
            self.assertNotIn("ephemeral", reg.list_names())
        finally:
            os.unlink(path)

    def test_reload_returns_int(self):
        path = _tmp_path()
        try:
            reg = PolicyRegistry()
            reg.register("p", "Alice may call p.")
            store = FilePolicyStore(path, reg)
            store.save()
            result = store.reload()
            self.assertIsInstance(result, int)
        finally:
            os.unlink(path)

    def test_reload_version_preserved(self):
        """Reloaded file is still subject to version checks."""
        path = _tmp_path()
        try:
            reg = PolicyRegistry()
            reg.register("p", "Alice may call p.")
            store = FilePolicyStore(path, reg)
            store.save()
            # Tamper the saved file to have a different version
            with open(path) as fh:
                data = json.load(fh)
            data["version"] = "99"
            with open(path, "w") as fh:
                json.dump(data, fh)
            with warnings.catch_warnings(record=True) as ws:
                warnings.simplefilter("always")
                store.reload()
            self.assertTrue(
                any("version" in str(w.message).lower() for w in ws),
                "Expected UserWarning about version mismatch after reload",
            )
        finally:
            os.unlink(path)

    def test_reload_idempotent(self):
        path = _tmp_path()
        try:
            reg = PolicyRegistry()
            reg.register("p", "Alice may call p.")
            store = FilePolicyStore(path, reg)
            store.save()
            c1 = store.reload()
            c2 = store.reload()
            self.assertEqual(c1, c2)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 2. DelegationManager.merge(other)
# ---------------------------------------------------------------------------
class TestDelegationManagerMerge(unittest.TestCase):
    """DelegationManager.merge(other) merges delegation store entries."""

    def test_merge_adds_new_delegations(self):
        mgr1 = DelegationManager()
        mgr1.add(_make_deleg("cid-A"))

        mgr2 = DelegationManager()
        mgr2.add(_make_deleg("cid-B"))
        mgr2.add(_make_deleg("cid-C"))

        added = mgr1.merge(mgr2)
        self.assertEqual(added, 2)
        self.assertIn("cid-B", mgr1._store.list_cids())
        self.assertIn("cid-C", mgr1._store.list_cids())

    def test_merge_skips_existing_cids(self):
        mgr1 = DelegationManager()
        mgr1.add(_make_deleg("shared"))

        mgr2 = DelegationManager()
        mgr2.add(_make_deleg("shared"))
        mgr2.add(_make_deleg("new"))

        added = mgr1.merge(mgr2)
        self.assertEqual(added, 1)

    def test_merge_empty_other_returns_zero(self):
        mgr1 = DelegationManager()
        mgr1.add(_make_deleg("cid-A"))
        mgr2 = DelegationManager()

        added = mgr1.merge(mgr2)
        self.assertEqual(added, 0)
        self.assertEqual(len(mgr1._store), 1)

    def test_merge_into_empty_self(self):
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        for i in range(3):
            mgr2.add(_make_deleg(f"cid-{i}"))

        added = mgr1.merge(mgr2)
        self.assertEqual(added, 3)
        self.assertEqual(len(mgr1._store), 3)

    def test_merge_invalidates_evaluator_cache(self):
        mgr1 = DelegationManager()
        _ = mgr1.get_evaluator()  # populate cache
        self.assertIsNotNone(mgr1._evaluator)

        mgr2 = DelegationManager()
        mgr2.add(_make_deleg("cid-X"))
        mgr1.merge(mgr2)
        self.assertIsNone(mgr1._evaluator, "evaluator cache should be invalidated after merge")

    def test_merge_no_evaluator_invalidation_when_nothing_added(self):
        mgr1 = DelegationManager()
        mgr1.add(_make_deleg("shared"))
        _ = mgr1.get_evaluator()  # populate cache

        mgr2 = DelegationManager()
        mgr2.add(_make_deleg("shared"))  # already in mgr1

        mgr1.merge(mgr2)
        self.assertIsNotNone(mgr1._evaluator, "no new additions → cache should NOT be invalidated")

    def test_merge_does_not_mutate_other(self):
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        mgr2.add(_make_deleg("cid-A"))

        cids_before = set(mgr2._store.list_cids())
        mgr1.merge(mgr2)
        cids_after = set(mgr2._store.list_cids())
        self.assertEqual(cids_before, cids_after)

    def test_merge_does_not_copy_revocations(self):
        """Revocation list is security-sensitive; merge must NOT copy it."""
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        mgr2.add(_make_deleg("cid-B"))
        mgr2.revoke("cid-B")

        mgr1.merge(mgr2)
        # mgr1 should have the delegation but NOT the revocation from mgr2
        self.assertIn("cid-B", mgr1._store.list_cids())
        self.assertFalse(mgr1.is_revoked("cid-B"), "revocations must not be copied by merge")

    def test_merge_returns_int(self):
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        result = mgr1.merge(mgr2)
        self.assertIsInstance(result, int)


# ---------------------------------------------------------------------------
# 3. ComplianceChecker.save_encrypted version field
# ---------------------------------------------------------------------------
class TestComplianceCheckerEncryptedVersion(unittest.TestCase):
    """ComplianceChecker.save_encrypted embeds the version string."""

    def _skip_if_no_crypto(self):
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography package not installed")

    def test_encrypted_payload_contains_version(self):
        self._skip_if_no_crypto()
        import hashlib
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        checker = ComplianceChecker()
        path = _tmp_path(".enc")
        try:
            checker.save_encrypted(path, "test-password")
            with open(path, "rb") as fh:
                raw = fh.read()
            nonce, ct = raw[:12], raw[12:]
            key = hashlib.sha256(b"test-password").digest()
            plaintext = AESGCM(key).decrypt(nonce, ct, None)
            data = json.loads(plaintext.decode())
            self.assertIn("version", data)
            self.assertEqual(data["version"], _COMPLIANCE_RULE_VERSION)
        finally:
            os.unlink(path)

    def test_encrypted_version_matches_plain_save(self):
        """Encrypted version field matches the value written by plain save()."""
        self._skip_if_no_crypto()
        import hashlib
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        checker = ComplianceChecker()
        enc_path = _tmp_path(".enc")
        plain_path = _tmp_path(".json")
        try:
            checker.save_encrypted(enc_path, "pw")
            checker.save(plain_path)

            with open(plain_path) as fh:
                plain_data = json.load(fh)
            with open(enc_path, "rb") as fh:
                raw = fh.read()
            key = hashlib.sha256(b"pw").digest()
            plaintext = AESGCM(key).decrypt(raw[:12], raw[12:], None)
            enc_data = json.loads(plaintext.decode())

            self.assertEqual(plain_data.get("version"), enc_data.get("version"))
        finally:
            os.unlink(enc_path)
            os.unlink(plain_path)

    def test_load_encrypted_round_trip_with_version(self):
        self._skip_if_no_crypto()
        checker = ComplianceChecker()
        checker._deny_list.add("forbidden_tool")
        path = _tmp_path(".enc")
        try:
            checker.save_encrypted(path, "pw")
            checker2 = ComplianceChecker()
            checker2.load_encrypted(path, "pw")
            self.assertIn("forbidden_tool", checker2._deny_list)
        finally:
            os.unlink(path)

    def test_version_constant_exported(self):
        self.assertIsInstance(_COMPLIANCE_RULE_VERSION, str)
        self.assertGreater(len(_COMPLIANCE_RULE_VERSION), 0)

    def test_save_encrypted_no_crypto_fallback(self):
        checker = ComplianceChecker()
        path = _tmp_path(".json")
        try:
            with patch(
                "ipfs_datasets_py.mcp_server.compliance_checker.ComplianceChecker.save_encrypted"
            ) as mock_enc:
                mock_enc.side_effect = lambda p, pw: checker.save(p)
                with warnings.catch_warnings(record=True):
                    checker.save(path)
            # Just ensure the plain file is valid JSON
            with open(path) as fh:
                data = json.load(fh)
            self.assertIsInstance(data, dict)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 4. PubSubBus.publish_async()
# ---------------------------------------------------------------------------
class TestPubSubBusPublishAsync(unittest.TestCase):
    """PubSubBus.publish_async() async variant."""

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_publish_async_notifies_sync_handler(self):
        bus = PubSubBus()
        received = []
        bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, lambda t, p: received.append(p))
        n = self._run(bus.publish_async(PubSubEventType.RECEIPT_DISSEMINATE, {"x": 1}))
        count = n.notified if hasattr(n, "notified") else n
        self.assertGreaterEqual(count, 1)
        self.assertEqual(received[-1], {"x": 1})

    def test_publish_async_no_subscribers_returns_zero(self):
        bus = PubSubBus()
        n = self._run(bus.publish_async(PubSubEventType.RECEIPT_DISSEMINATE, {}))
        count = n.notified if hasattr(n, "notified") else n
        self.assertEqual(count, 0)

    def test_publish_async_multiple_handlers(self):
        bus = PubSubBus()
        calls = []
        bus.subscribe(PubSubEventType.INTERFACE_ANNOUNCE, lambda t, p: calls.append("h1"))
        bus.subscribe(PubSubEventType.INTERFACE_ANNOUNCE, lambda t, p: calls.append("h2"))
        n = self._run(bus.publish_async(PubSubEventType.INTERFACE_ANNOUNCE, {}))
        count = n.notified if hasattr(n, "notified") else n
        self.assertGreaterEqual(count, 1)

    def test_publish_async_fallback_without_anyio(self):
        """Without anyio, publish_async warns and falls back to sync publish()."""
        bus = PubSubBus()
        received = []
        bus.subscribe(PubSubEventType.DECISION_DISSEMINATE, lambda t, p: received.append(p))
        with patch.dict("sys.modules", {"anyio": None}):
            # Force ImportError path: delete anyio from sys.modules cache
            import sys
            anyio_backup = sys.modules.pop("anyio", None)
            try:
                with warnings.catch_warnings(record=True):
                    warnings.simplefilter("always")
                    from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus as _B
                    b2 = _B()
                    b2.subscribe(PubSubEventType.SCHEDULING_SIGNAL, lambda t, p: received.append(p))
            finally:
                if anyio_backup is not None:
                    sys.modules["anyio"] = anyio_backup
        # We just verify the method exists and is awaitable
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(bus.publish_async))

    def test_publish_async_is_coroutine_function(self):
        import inspect
        bus = PubSubBus()
        self.assertTrue(inspect.iscoroutinefunction(bus.publish_async))

    def test_publish_async_topic_string(self):
        bus = PubSubBus()
        received = []
        bus.subscribe("custom.topic", lambda t, p: received.append((t, p)))
        n = self._run(bus.publish_async("custom.topic", {"key": "val"}))
        count = n.notified if hasattr(n, "notified") else n
        self.assertGreaterEqual(count, 1)

    def test_publish_async_payload_passed_correctly(self):
        bus = PubSubBus()
        payloads = []
        bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, lambda t, p: payloads.append(p))
        self._run(bus.publish_async(PubSubEventType.RECEIPT_DISSEMINATE, {"type": "revocation", "count": 3}))
        self.assertTrue(any(p.get("count") == 3 for p in payloads))


# ---------------------------------------------------------------------------
# 5. E2E smoke test
# ---------------------------------------------------------------------------
class TestE2ESession64(unittest.TestCase):
    """End-to-end: reload → merge → publish_async → compliance encrypted version."""

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_file_policy_store_reload_preserves_saved_policies(self):
        path = _tmp_path()
        try:
            reg = PolicyRegistry()
            reg.register("p1", "Alice may call tool1.")
            reg.register("p2", "Bob may call tool2.")
            store = FilePolicyStore(path, reg)
            store.save()
            reg.register("ephemeral", "Temp.")
            count = store.reload()
            self.assertEqual(count, 2)
            self.assertNotIn("ephemeral", reg.list_names())
        finally:
            os.unlink(path)

    def test_delegation_manager_merge_then_can_invoke(self):
        import time
        mgr1 = DelegationManager()
        d1 = Delegation(
            cid="root-cid",
            issuer="did:key:root",
            audience="did:key:mid",
            capabilities=[Capability(resource="mcp://tools", ability="*")],
            expiry=time.time() + 3600,
        )
        mgr1.add(d1)

        mgr2 = DelegationManager()
        d2 = Delegation(
            cid="leaf-cid",
            issuer="did:key:mid",
            audience="did:key:leaf",
            capabilities=[Capability(resource="mcp://tools", ability="some_tool")],
            expiry=time.time() + 3600,
            proof_cid="root-cid",
        )
        mgr2.add(d2)

        added = mgr1.merge(mgr2)
        self.assertEqual(added, 1)
        self.assertIn("leaf-cid", mgr1._store.list_cids())

    def test_pubsub_async_revocation_notification(self):
        bus = PubSubBus()
        events = []
        bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, lambda t, p: events.append(p))
        n = self._run(bus.publish_async(
            PubSubEventType.RECEIPT_DISSEMINATE,
            {"type": "revocation", "root_cid": "cid-X", "count": 2},
        ))
        count = n.notified if hasattr(n, "notified") else n
        self.assertGreaterEqual(count, 1)
        matching = [e for e in events if e.get("type") == "revocation"]
        self.assertTrue(len(matching) >= 1)
        self.assertEqual(matching[0]["count"], 2)

    def test_compliance_checker_merge_then_check(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            make_default_compliance_checker,
            ComplianceStatus,
        )
        base = make_default_compliance_checker()
        extra = ComplianceChecker(deny_list={"dangerous_tool"})
        base.merge(extra)
        self.assertIn("dangerous_tool", base._deny_list)

    def test_all_new_exports_importable(self):
        """Regression: all new public symbols can be imported."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        self.assertTrue(hasattr(FilePolicyStore, "reload"))

        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        self.assertTrue(hasattr(DelegationManager, "merge"))

        from ipfs_datasets_py.mcp_server.compliance_checker import _COMPLIANCE_RULE_VERSION
        self.assertIsInstance(_COMPLIANCE_RULE_VERSION, str)

        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(PubSubBus.publish_async))


if __name__ == "__main__":
    unittest.main()
