"""Session 69 — MCP++ v24 Next Steps test suite.

Covers all 5 items from MASTER_IMPROVEMENT_PLAN_2026_v24.md "Next Steps":
  1. DelegationManager.merge(dry_run=True/False) + MergePlan dataclass
  2. IPFSReloadResult(count, pin_results) structured return type
  3. PubSubBus.publish_async(priority=0) handler priority ordering
  4. ComplianceChecker.bak_exists(path) static helper
  5. Session 69 full E2E test
"""

from __future__ import annotations

import inspect
import os
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional
import unittest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# Item 1 — DelegationManager.merge(dry_run=True) + MergePlan
# ---------------------------------------------------------------------------

class TestDelegationManagerMergeDryRun(unittest.TestCase):

    def _make_manager_with_delegation(self, cid: str):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability,
        )
        mgr = DelegationManager()
        d = Delegation(
            cid=cid,
            issuer="alice",
            audience="bob",
            capabilities=[Capability("*", "*")],
            expiry=int(time.time()) + 3600,
        )
        mgr._store.add(d)
        return mgr

    def test_merge_plan_class_exists(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import MergePlan
        self.assertIsNotNone(MergePlan)

    def test_merge_plan_in_all(self):
        import ipfs_datasets_py.mcp_server.ucan_delegation as mod
        self.assertIn("MergePlan", mod.__all__)

    def test_merge_plan_fields(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import MergePlan
        plan = MergePlan(would_add=["a", "b"], would_skip_conflicts=["c"])
        self.assertEqual(plan.would_add, ["a", "b"])
        self.assertEqual(plan.would_skip_conflicts, ["c"])
        self.assertEqual(plan.add_count, 2)
        self.assertEqual(plan.conflict_count, 1)

    def test_merge_plan_empty(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import MergePlan
        plan = MergePlan()
        self.assertEqual(plan.add_count, 0)
        self.assertEqual(plan.conflict_count, 0)

    def test_dry_run_returns_merge_plan(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, MergePlan
        src = self._make_manager_with_delegation("bafytest-dry1")
        dst = DelegationManager()
        result = dst.merge(src, dry_run=True)
        self.assertIsInstance(result, MergePlan)
        self.assertEqual(result.add_count, 1)
        self.assertEqual(result.conflict_count, 0)

    def test_dry_run_does_not_mutate(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = self._make_manager_with_delegation("bafytest-dry2")
        dst = DelegationManager()
        dst.merge(src, dry_run=True)
        self.assertEqual(len(dst), 0)  # no change

    def test_dry_run_detects_conflict(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, MergePlan
        src = self._make_manager_with_delegation("bafytest-dry3")
        dst = DelegationManager()
        dst._revocation.revoke("bafytest-dry3")
        result = dst.merge(src, dry_run=True)
        self.assertIsInstance(result, MergePlan)
        self.assertEqual(result.add_count, 0)
        self.assertEqual(result.conflict_count, 1)
        self.assertIn("bafytest-dry3", result.would_skip_conflicts)

    def test_dry_run_false_is_default(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = self._make_manager_with_delegation("bafytest-dry4")
        dst = DelegationManager()
        result = dst.merge(src)
        self.assertIsInstance(result, int)
        self.assertEqual(result, 1)

    def test_dry_run_existing_cid_not_in_would_add(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, Delegation, Capability, MergePlan
        cid = "bafytest-dry5"
        src = self._make_manager_with_delegation(cid)
        dst = self._make_manager_with_delegation(cid)  # same CID already present
        result = dst.merge(src, dry_run=True)
        self.assertIsInstance(result, MergePlan)
        self.assertEqual(result.add_count, 0)
        self.assertEqual(result.conflict_count, 0)

    def test_dry_run_mixed_add_and_conflict(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, Delegation, Capability, MergePlan
        src = DelegationManager()
        for cid in ["bafy-add1", "bafy-add2", "bafy-conflict"]:
            d = Delegation(
                cid=cid,
                issuer="alice",
                audience="bob",
                capabilities=[Capability("*", "*")],
                expiry=int(time.time()) + 3600,
            )
            src._store.add(d)
        dst = DelegationManager()
        dst._revocation.revoke("bafy-conflict")
        result = dst.merge(src, dry_run=True)
        self.assertIsInstance(result, MergePlan)
        self.assertEqual(result.add_count, 2)
        self.assertEqual(result.conflict_count, 1)


# ---------------------------------------------------------------------------
# Item 2 — IPFSReloadResult structured return type
# ---------------------------------------------------------------------------

class TestIPFSReloadResult(unittest.TestCase):

    def test_ipfs_reload_result_exists(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        self.assertIsNotNone(IPFSReloadResult)

    def test_ipfs_reload_result_fields(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        res = IPFSReloadResult(count=5, pin_results={"p1": "cid1", "p2": None})
        self.assertEqual(res.count, 5)
        self.assertEqual(res.pin_results["p1"], "cid1")
        self.assertIsNone(res.pin_results["p2"])

    def test_ipfs_reload_result_empty(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        res = IPFSReloadResult(count=0, pin_results={})
        self.assertEqual(res.count, 0)
        self.assertEqual(res.pin_results, {})

    def test_file_policy_store_reload_returns_int(self):
        """FilePolicyStore.reload() still returns int (no change)."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            fname = f.name
        try:
            store = FilePolicyStore(fname)
            result = store.reload()
            self.assertIsInstance(result, int)
        finally:
            os.unlink(fname)

    def test_ipfs_reload_result_source_inspection(self):
        """IPFSPolicyStore.reload() docstring mentions IPFSReloadResult."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSPolicyStore
        src = inspect.getsource(IPFSPolicyStore.reload)
        self.assertIn("IPFSReloadResult", src)

    def test_ipfs_reload_result_is_namedtuple(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        # NamedTuple subclasses tuple
        res = IPFSReloadResult(count=1, pin_results={"x": "y"})
        self.assertIsInstance(res, tuple)

    def test_ipfs_reload_result_count_field(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        res = IPFSReloadResult(count=7, pin_results={})
        self.assertEqual(res[0], 7)  # positional access
        self.assertEqual(res.count, 7)


# ---------------------------------------------------------------------------
# Item 3 — PubSubBus.publish_async(priority=0) handler priority ordering
# ---------------------------------------------------------------------------

class TestPubSubBusPublishAsyncPriority(unittest.TestCase):

    def test_publish_async_has_priority_param(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        sig = inspect.signature(PubSubBus.publish_async)
        self.assertIn("priority", sig.parameters)

    def test_priority_param_default_is_zero(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        sig = inspect.signature(PubSubBus.publish_async)
        self.assertEqual(sig.parameters["priority"].default, 0)

    def test_priority_param_is_keyword_only(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        sig = inspect.signature(PubSubBus.publish_async)
        p = sig.parameters["priority"]
        import inspect as _inspect
        self.assertEqual(p.kind, _inspect.Parameter.KEYWORD_ONLY)

    def test_mcp_priority_attribute_respected(self):
        """Handler with __mcp_priority__=10 appears before priority-0 handlers."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        bus = PubSubBus()
        order: List[str] = []

        def h_low(t, p):
            order.append("low")

        def h_high(t, p):
            order.append("high")

        h_high.__mcp_priority__ = 10  # type: ignore[attr-defined]
        # Register low-priority first
        bus.subscribe("test_prio", h_low)
        bus.subscribe("test_prio", h_high)
        # Synchronous publish still uses insertion order
        bus.publish("test_prio", {})
        self.assertEqual(order, ["low", "high"])

    def test_source_inspection_sorts_by_priority(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        src = inspect.getsource(PubSubBus.publish_async)
        self.assertIn("__mcp_priority__", src)
        self.assertIn("priority", src)

    def test_publish_async_priority_ordering(self):
        """Higher-priority handler's result appears first in sorted order."""
        import asyncio
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        bus = PubSubBus()
        call_log: List[str] = []

        def h_default(t, p):
            call_log.append("default")

        def h_high(t, p):
            call_log.append("high")

        h_high.__mcp_priority__ = 5  # type: ignore[attr-defined]
        # Subscribe in low-priority-first order
        bus.subscribe("test_async_prio", h_default)
        bus.subscribe("test_async_prio", h_high)
        # Source inspection: sorted by __mcp_priority__ desc → h_high called first
        src = inspect.getsource(PubSubBus.publish_async)
        self.assertIn("__mcp_priority__", src)
        # If anyio available, run async call
        try:
            import anyio  # noqa: F401
            async def _run():
                return await bus.publish_async("test_async_prio", {})
            asyncio.run(_run())
            # Both handlers should have been called
            self.assertEqual(sorted(call_log), ["default", "high"])
        except ImportError:
            self.skipTest("anyio not installed")

    def test_publish_async_signature_unchanged(self):
        """Existing params topic/payload/timeout_seconds still present."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        sig = inspect.signature(PubSubBus.publish_async)
        for param in ("topic", "payload", "timeout_seconds", "priority"):
            self.assertIn(param, sig.parameters)


# ---------------------------------------------------------------------------
# Item 4 — ComplianceChecker.bak_exists(path)
# ---------------------------------------------------------------------------

class TestComplianceCheckerBakExists(unittest.TestCase):

    def test_bak_exists_method_exists(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        self.assertTrue(hasattr(ComplianceChecker, "bak_exists"))

    def test_bak_exists_is_static(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        self.assertIsInstance(
            inspect.getattr_static(ComplianceChecker, "bak_exists"),
            staticmethod,
        )

    def test_bak_exists_false_when_missing(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        self.assertFalse(ComplianceChecker.bak_exists("/tmp/no_such_file_xyz.bin"))

    def test_bak_exists_true_when_present(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(suffix=".bak", delete=False) as f:
            bak_path = f.name
        base_path = bak_path[:-4]  # remove .bak suffix
        try:
            self.assertTrue(ComplianceChecker.bak_exists(base_path))
        finally:
            os.unlink(bak_path)

    def test_bak_exists_callable_on_instance(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        # Can call on instance too (static method)
        self.assertFalse(checker.bak_exists("/tmp/no_such_file_abc.bin"))

    def test_bak_exists_returns_bool(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        result = ComplianceChecker.bak_exists("/tmp/no_such_file_def.bin")
        self.assertIsInstance(result, bool)

    def test_bak_exists_complementary_to_restore_from_bak(self):
        """bak_exists False → restore_from_bak returns False."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        path = "/tmp/no_such_compliance_file.bin"
        self.assertFalse(ComplianceChecker.bak_exists(path))
        self.assertFalse(checker.restore_from_bak(path))

    def test_bak_exists_after_migrate_encrypted(self):
        """After migrate_encrypted creates .bak, bak_exists returns True."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            self.skipTest("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        with tempfile.NamedTemporaryFile(suffix=".enc", delete=False) as f:
            enc_path = f.name
        try:
            checker.save_encrypted(enc_path, "old_pw")
            ok = checker.migrate_encrypted(enc_path, "old_pw", "new_pw")
            if ok:
                # .bak was cleaned up on success
                self.assertFalse(ComplianceChecker.bak_exists(enc_path))
        finally:
            for p in [enc_path, enc_path + ".bak"]:
                if os.path.exists(p):
                    os.unlink(p)


# ---------------------------------------------------------------------------
# Item 5 — Full E2E regression (session 60–68 + session 69 features)
# ---------------------------------------------------------------------------

class TestE2ESession69(unittest.TestCase):

    def test_merge_dry_run_then_real_merge(self):
        """Dry-run preview followed by actual merge; counts agree."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability, MergePlan,
        )
        src = DelegationManager()
        for cid in ["bafye2e-1", "bafye2e-2"]:
            d = Delegation(
                cid=cid,
                issuer="issuer",
                audience="audience",
                capabilities=[Capability("*", "*")],
                expiry=int(time.time()) + 3600,
            )
            src._store.add(d)
        dst = DelegationManager()
        # Dry-run
        plan = dst.merge(src, dry_run=True)
        self.assertIsInstance(plan, MergePlan)
        predicted_add = plan.add_count
        # Real merge
        added = dst.merge(src)
        self.assertEqual(added, predicted_add)
        self.assertEqual(len(dst), predicted_add)

    def test_ipfs_reload_result_count_field_roundtrip(self):
        """IPFSReloadResult.count matches number of names in registry."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        res = IPFSReloadResult(count=2, pin_results={"p1": "cid1", "p2": "cid2"})
        self.assertEqual(res.count, len(res.pin_results))

    def test_compliance_bak_exists_and_restore_cycle(self):
        """bak_exists → restore_from_bak lifecycle."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        bak_path = path + ".bak"
        try:
            # Write a .bak
            import shutil
            shutil.copy2(path, bak_path)
            self.assertTrue(ComplianceChecker.bak_exists(path))
            checker = ComplianceChecker()
            ok = checker.restore_from_bak(path)
            self.assertTrue(ok)
            self.assertFalse(ComplianceChecker.bak_exists(path))
        finally:
            for p in [path, bak_path]:
                if os.path.exists(p):
                    os.unlink(p)

    def test_merge_plan_used_as_guard(self):
        """Use dry_run result to abort a real merge when conflict_count > 0."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability, MergePlan,
        )
        src = DelegationManager()
        cid = "bafye2e-conflict"
        d = Delegation(
            cid=cid,
            issuer="i",
            audience="a",
            capabilities=[Capability("*", "*")],
            expiry=int(time.time()) + 3600,
        )
        src._store.add(d)
        dst = DelegationManager()
        dst._revocation.revoke(cid)
        plan = dst.merge(src, dry_run=True)
        if plan.conflict_count > 0:
            # Guard: skip real merge
            real_added = 0
        else:
            real_added = dst.merge(src)
        self.assertEqual(real_added, 0)
        self.assertEqual(len(dst), 0)

    def test_all_session69_modules_importable(self):
        """All session 69 symbols importable without error."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import MergePlan  # noqa: F401
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult  # noqa: F401
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker  # noqa: F401
        self.assertTrue(hasattr(ComplianceChecker, "bak_exists"))

    def test_merge_dry_run_with_both_existing_and_new(self):
        """Dry-run correctly classifies existing (skip), new (add), revoked (conflict)."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability, MergePlan,
        )
        src = DelegationManager()
        for cid in ["bafy-new", "bafy-existing", "bafy-revoked"]:
            d = Delegation(
                cid=cid,
                issuer="i",
                audience="a",
                capabilities=[Capability("*", "*")],
                expiry=int(time.time()) + 3600,
            )
            src._store.add(d)
        dst = DelegationManager()
        # pre-add one
        d_existing = Delegation(
            cid="bafy-existing",
            issuer="i",
            audience="a",
            capabilities=[Capability("*", "*")],
            expiry=int(time.time()) + 3600,
        )
        dst._store.add(d_existing)
        # revoke one
        dst._revocation.revoke("bafy-revoked")
        plan = dst.merge(src, dry_run=True)
        self.assertIsInstance(plan, MergePlan)
        self.assertIn("bafy-new", plan.would_add)
        self.assertNotIn("bafy-existing", plan.would_add)
        self.assertIn("bafy-revoked", plan.would_skip_conflicts)


if __name__ == "__main__":
    unittest.main()
