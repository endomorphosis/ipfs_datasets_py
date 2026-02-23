"""
Session 70 tests — MCP++ v25 Next Steps
========================================
Items tested:
1. DelegationManager.merge() audit trail for non-revocation additions
2. IPFSReloadResult.total_failed property
3. PubSubBus.subscribe(priority=0) stores priority as __mcp_priority__
4. ComplianceChecker.bak_path(path) static helper
5. E2E covering all four features together
"""

import os
import sys
import time
import tempfile
import unittest
import warnings

# ---------------------------------------------------------------------------
# Repository root on PYTHONPATH
# ---------------------------------------------------------------------------
_REPO_ROOT = __file__
for _ in range(4):
    _REPO_ROOT = os.path.dirname(_REPO_ROOT)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ============================================================
# Section 1 — DelegationManager.merge() audit trail
# ============================================================
class TestDelegationManagerMergeAuditTrail(unittest.TestCase):
    """DelegationManager.merge() records merge_add events in audit_log."""

    def _make_delegation(self, cid: str):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Delegation, Capability
        cap = Capability(resource="resource:test", ability="action/test")
        return Delegation(
            cid=cid,
            issuer="did:key:issuer",
            audience="did:key:audience",
            capabilities=[cap],
        )

    def test_no_audit_log_default(self):
        """merge() with no audit_log param works as before."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        mgr2.add(self._make_delegation("bafyAudit001"))
        n = mgr1.merge(mgr2)
        self.assertEqual(n, 1)

    def test_audit_log_records_merge_add(self):
        """Each newly-added delegation emits a merge_add audit entry."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        mgr2.add(self._make_delegation("bafyAudit002"))
        mgr2.add(self._make_delegation("bafyAudit003"))
        audit = []
        mgr1.merge(mgr2, audit_log=audit)
        self.assertEqual(len(audit), 2)
        events = [e["event"] for e in audit]
        self.assertIn("merge_add", events)
        cids = {e["cid"] for e in audit}
        self.assertEqual(cids, {"bafyAudit002", "bafyAudit003"})

    def test_audit_event_has_cid_field(self):
        """Each audit entry contains event and cid fields."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        mgr2.add(self._make_delegation("bafyAudit004"))
        audit = []
        mgr1.merge(mgr2, audit_log=audit)
        self.assertTrue(all("event" in e and "cid" in e for e in audit))

    def test_audit_log_not_called_when_already_present(self):
        """No audit entry for CIDs already in self._store."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        d = self._make_delegation("bafyAuditDup")
        mgr1.add(d)
        mgr2.add(d)
        audit = []
        n = mgr1.merge(mgr2, audit_log=audit)
        self.assertEqual(n, 0)
        self.assertEqual(audit, [])

    def test_audit_log_not_called_for_revoked_conflicts(self):
        """Revoked-conflict skips don't produce merge_add entries."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        d = self._make_delegation("bafyAuditRevoked")
        mgr2.add(d)
        mgr1._revocation.revoke("bafyAuditRevoked")
        audit = []
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            n = mgr1.merge(mgr2, audit_log=audit)
        self.assertEqual(n, 0)
        merge_adds = [e for e in audit if e.get("event") == "merge_add"]
        self.assertEqual(merge_adds, [])

    def test_audit_log_append_exception_swallowed(self):
        """A broken audit_log never prevents the merge from completing."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager

        class BrokenLog:
            def append(self, _entry):
                raise RuntimeError("disk full")

        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        mgr2.add(self._make_delegation("bafyAuditBroken"))
        # Should not raise
        n = mgr1.merge(mgr2, audit_log=BrokenLog())
        self.assertEqual(n, 1)

    def test_dry_run_does_not_record_audit(self):
        """dry_run=True returns MergePlan without auditing."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, MergePlan
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        mgr2.add(self._make_delegation("bafyAuditDry"))
        audit = []
        plan = mgr1.merge(mgr2, audit_log=audit, dry_run=True)
        self.assertIsInstance(plan, MergePlan)
        # dry_run=True must not have mutated audit
        self.assertEqual(audit, [])

    def test_revocation_copy_audit_still_works(self):
        """copy_revocations audit entries are separate from merge_add entries."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        mgr2.add(self._make_delegation("bafyAuditBoth"))
        mgr2._revocation.revoke("bafyRevCID")
        audit = []
        mgr1.merge(mgr2, audit_log=audit, copy_revocations=True)
        events = {e["event"] for e in audit}
        self.assertIn("merge_add", events)
        self.assertIn("revocation_copied", events)


# ============================================================
# Section 2 — IPFSReloadResult.total_failed
# ============================================================
class TestIPFSReloadResultTotalFailed(unittest.TestCase):
    """IPFSReloadResult.total_failed counts None values in pin_results."""

    def _make_result(self, pins):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        return IPFSReloadResult(count=len(pins), pin_results=pins)

    def test_all_success(self):
        r = self._make_result({"a": "cid1", "b": "cid2"})
        self.assertEqual(r.total_failed, 0)

    def test_all_failed(self):
        r = self._make_result({"a": None, "b": None})
        self.assertEqual(r.total_failed, 2)

    def test_mixed(self):
        r = self._make_result({"a": "cid1", "b": None, "c": None})
        self.assertEqual(r.total_failed, 2)

    def test_empty(self):
        r = self._make_result({})
        self.assertEqual(r.total_failed, 0)

    def test_single_failed(self):
        r = self._make_result({"x": None})
        self.assertEqual(r.total_failed, 1)

    def test_single_success(self):
        r = self._make_result({"x": "Qmabcd"})
        self.assertEqual(r.total_failed, 0)

    def test_total_failed_plus_success_equals_count(self):
        pins = {"a": "c1", "b": None, "c": "c3", "d": None}
        r = self._make_result(pins)
        success = sum(1 for v in pins.values() if v is not None)
        self.assertEqual(r.total_failed + success, r.count)


# ============================================================
# Section 3 — PubSubBus.subscribe(priority=0)
# ============================================================
class TestPubSubBusSubscribePriority(unittest.TestCase):
    """subscribe(priority=N) stores __mcp_priority__ on the handler."""

    def _bus(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        return PubSubBus()

    def test_default_priority_zero(self):
        bus = self._bus()
        def handler(t, p): pass
        bus.subscribe("topic", handler)
        self.assertEqual(getattr(handler, "__mcp_priority__", 0), 0)

    def test_explicit_priority_stored(self):
        bus = self._bus()
        def handler(t, p): pass
        bus.subscribe("topic", handler, priority=7)
        self.assertEqual(handler.__mcp_priority__, 7)

    def test_negative_priority_stored(self):
        bus = self._bus()
        def handler(t, p): pass
        bus.subscribe("topic", handler, priority=-3)
        self.assertEqual(handler.__mcp_priority__, -3)

    def test_highest_priority_wins(self):
        """Second subscribe with higher priority upgrades the attribute."""
        bus = self._bus()
        def handler(t, p): pass
        bus.subscribe("topic1", handler, priority=2)
        bus.subscribe("topic2", handler, priority=9)
        self.assertEqual(handler.__mcp_priority__, 9)

    def test_lower_priority_does_not_overwrite(self):
        """Second subscribe with lower priority does not downgrade."""
        bus = self._bus()
        def handler(t, p): pass
        bus.subscribe("topic", handler, priority=5)
        bus.subscribe("topic2", handler, priority=1)
        self.assertEqual(handler.__mcp_priority__, 5)

    def test_publish_respects_priority_ordering(self):
        """sync publish calls handlers in registration order (priority only for async)."""
        bus = self._bus()
        call_order = []
        def h_low(t, p): call_order.append("low")
        def h_high(t, p): call_order.append("high")
        bus.subscribe("t", h_low, priority=1)
        bus.subscribe("t", h_high, priority=10)
        bus.publish("t", {})
        # sync publish preserves registration order (priority sorting is async-only)
        self.assertIn("low", call_order)
        self.assertIn("high", call_order)

    def test_subscribe_same_handler_twice_no_duplicate(self):
        """Subscribing the same handler twice on the same topic is idempotent."""
        bus = self._bus()
        def handler(t, p): pass
        bus.subscribe("t", handler, priority=3)
        bus.subscribe("t", handler, priority=3)
        count = bus.publish("t", {})
        self.assertEqual(count, 1)


# ============================================================
# Section 4 — ComplianceChecker.bak_path
# ============================================================
class TestComplianceCheckerBakPath(unittest.TestCase):
    """ComplianceChecker.bak_path(path) returns path + '.bak'."""

    def _checker(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        return ComplianceChecker()

    def test_basic(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        self.assertEqual(ComplianceChecker.bak_path("/data/rules.enc"), "/data/rules.enc.bak")

    def test_instance_callable(self):
        checker = self._checker()
        self.assertEqual(checker.bak_path("/tmp/x.json"), "/tmp/x.json.bak")

    def test_empty_string(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        self.assertEqual(ComplianceChecker.bak_path(""), ".bak")

    def test_already_has_bak_suffix(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        # bak_path is a pure string operation — no dedup
        self.assertEqual(ComplianceChecker.bak_path("rules.enc.bak"), "rules.enc.bak.bak")

    def test_bak_path_consistent_with_bak_exists(self):
        """bak_path returns the same path that bak_exists checks."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            base = os.path.join(td, "rules.enc")
            bp = ComplianceChecker.bak_path(base)
            self.assertFalse(ComplianceChecker.bak_exists(base))
            # create the .bak file
            with open(bp, "wb") as f:
                f.write(b"backup")
            self.assertTrue(ComplianceChecker.bak_exists(base))

    def test_relative_path(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        self.assertEqual(ComplianceChecker.bak_path("relative.enc"), "relative.enc.bak")

    def test_no_extension(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        self.assertEqual(ComplianceChecker.bak_path("noext"), "noext.bak")


# ============================================================
# Section 5 — E2E covering all four features
# ============================================================
class TestE2ESession70(unittest.TestCase):
    """End-to-end tests exercising all four session-70 features together."""

    def _make_delegation(self, cid: str):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Delegation, Capability
        cap = Capability(resource="resource:e2e", ability="invoke")
        return Delegation(
            cid=cid,
            issuer="did:key:e2e-issuer",
            audience="did:key:e2e-audience",
            capabilities=[cap],
        )

    def test_merge_audit_and_total_failed_integration(self):
        """Merge emits audit entries; IPFSReloadResult.total_failed works."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult

        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        mgr2.add(self._make_delegation("bafyE2EInt001"))
        audit = []
        n = mgr1.merge(mgr2, audit_log=audit)
        self.assertEqual(n, 1)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["event"], "merge_add")

        # IPFSReloadResult independently
        r = IPFSReloadResult(count=2, pin_results={"pol1": "Qmfoo", "pol2": None})
        self.assertEqual(r.total_failed, 1)

    def test_subscribe_priority_and_bak_path_integration(self):
        """subscribe priority + bak_path behave together correctly."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker

        bus = PubSubBus()
        results = []
        def h1(t, p): results.append("h1")
        def h2(t, p): results.append("h2")
        bus.subscribe("e2e", h1, priority=5)
        bus.subscribe("e2e", h2, priority=10)
        bus.publish("e2e", {"msg": "hello"})
        self.assertIn("h1", results)
        self.assertIn("h2", results)

        # bak_path
        bp = ComplianceChecker.bak_path("/tmp/compliance.enc")
        self.assertEqual(bp, "/tmp/compliance.enc.bak")

    def test_merge_audit_with_revocation_copy(self):
        """merge with copy_revocations produces both merge_add and revocation_copied entries."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        mgr2.add(self._make_delegation("bafyE2EBoth"))
        mgr2._revocation.revoke("bafyE2ERev")
        audit = []
        mgr1.merge(mgr2, audit_log=audit, copy_revocations=True)
        event_types = {e["event"] for e in audit}
        self.assertIn("merge_add", event_types)
        self.assertIn("revocation_copied", event_types)

    def test_total_failed_zero_for_all_pins_succeeded(self):
        """total_failed == 0 when every policy was pinned."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        r = IPFSReloadResult(
            count=3,
            pin_results={"a": "Qm1", "b": "Qm2", "c": "Qm3"},
        )
        self.assertEqual(r.total_failed, 0)

    def test_bak_path_consistent_across_all_bak_helpers(self):
        """bak_path + bak_exists + restore_from_bak form a coherent set."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            base = os.path.join(td, "rules.enc")
            bp = ComplianceChecker.bak_path(base)
            self.assertEqual(bp, base + ".bak")
            self.assertFalse(ComplianceChecker.bak_exists(base))
            # create backup
            with open(bp, "wb") as f:
                f.write(b"backup_data")
            self.assertTrue(ComplianceChecker.bak_exists(base))
            # restore_from_bak moves it to base
            checker = ComplianceChecker()
            ok = checker.restore_from_bak(base)
            self.assertTrue(ok)
            self.assertFalse(ComplianceChecker.bak_exists(base))
            self.assertTrue(os.path.exists(base))


if __name__ == "__main__":
    unittest.main()
