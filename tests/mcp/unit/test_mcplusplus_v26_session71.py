"""
Session 71 tests — MCP++ v26 Next Steps
========================================
Items tested:
1. DelegationManager.merge() returns MergeResult (added_count/conflict_count/revocations_copied)
2. IPFSReloadResult.success_rate property
3. PubSubBus.subscribe() returns subscription ID + unsubscribe_by_id(sid)
4. ComplianceChecker.rotate_bak(path, max_keep=3)
5. E2E covering all four features together
"""

import os
import sys
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
# Section 1 — MergeResult dataclass + merge() return type
# ============================================================
class TestMergeResult(unittest.TestCase):
    """DelegationManager.merge(dry_run=False) returns MergeResult."""

    def _make_delegation(self, cid: str):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Delegation, Capability
        cap = Capability(resource="resource:test", ability="action/test")
        return Delegation(
            cid=cid,
            issuer="did:key:issuer",
            audience="did:key:audience",
            capabilities=[cap],
        )

    def test_merge_returns_merge_result_instance(self):
        """merge() returns a MergeResult, not a bare int."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, MergeResult
        src = DelegationManager()
        src.add(self._make_delegation("bafyMR001"))
        dst = DelegationManager()
        result = dst.merge(src)
        self.assertIsInstance(result, MergeResult)

    def test_merge_result_added_count(self):
        """MergeResult.added_count reflects delegations added."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        src.add(self._make_delegation("bafyMR002"))
        src.add(self._make_delegation("bafyMR003"))
        dst = DelegationManager()
        result = dst.merge(src)
        self.assertEqual(result.added_count, 2)

    def test_merge_result_conflict_count(self):
        """MergeResult.conflict_count counts revoked CIDs skipped."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        src.add(self._make_delegation("bafyMRConflict"))
        dst = DelegationManager()
        dst._revocation.revoke("bafyMRConflict")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = dst.merge(src)
        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.added_count, 0)

    def test_merge_result_revocations_copied(self):
        """MergeResult.revocations_copied counts when copy_revocations=True."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        src.add(self._make_delegation("bafyMRRev001"))
        src._revocation.revoke("bafyMRRev001")
        dst = DelegationManager()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = dst.merge(src, copy_revocations=True)
        self.assertEqual(result.revocations_copied, 1)

    def test_merge_result_revocations_not_copied_by_default(self):
        """revocations_copied is 0 when copy_revocations=False (default)."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        src.add(self._make_delegation("bafyMRRev002"))
        src._revocation.revoke("bafyMRRev002")
        dst = DelegationManager()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = dst.merge(src)
        self.assertEqual(result.revocations_copied, 0)

    def test_merge_result_int_conversion(self):
        """int(MergeResult) returns added_count for backward compat."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        src.add(self._make_delegation("bafyMRInt001"))
        dst = DelegationManager()
        result = dst.merge(src)
        self.assertEqual(int(result), 1)

    def test_merge_result_equality_with_int(self):
        """MergeResult == int compares added_count."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        src.add(self._make_delegation("bafyMREq001"))
        dst = DelegationManager()
        result = dst.merge(src)
        self.assertEqual(result, 1)

    def test_merge_result_in_all(self):
        """MergeResult is exported from ucan_delegation.__all__."""
        from ipfs_datasets_py.mcp_server import ucan_delegation
        self.assertIn("MergeResult", ucan_delegation.__all__)

    def test_dry_run_still_returns_merge_plan(self):
        """dry_run=True still returns a MergePlan, not MergeResult."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, MergePlan
        src = DelegationManager()
        src.add(self._make_delegation("bafyMRDry001"))
        dst = DelegationManager()
        result = dst.merge(src, dry_run=True)
        self.assertIsInstance(result, MergePlan)

    def test_merge_result_empty_merge(self):
        """Merging empty source yields MergeResult(0, 0, 0)."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, MergeResult
        src = DelegationManager()
        dst = DelegationManager()
        result = dst.merge(src)
        self.assertIsInstance(result, MergeResult)
        self.assertEqual(result.added_count, 0)
        self.assertEqual(result.conflict_count, 0)
        self.assertEqual(result.revocations_copied, 0)


# ============================================================
# Section 2 — IPFSReloadResult.success_rate property
# ============================================================
class TestIPFSReloadResultSuccessRate(unittest.TestCase):
    """IPFSReloadResult.success_rate fractional property."""

    def _make_result(self, count, pin_results):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        return IPFSReloadResult(count=count, pin_results=pin_results)

    def test_all_success(self):
        """All pins successful → success_rate == 1.0."""
        result = self._make_result(3, {"a": "cid1", "b": "cid2", "c": "cid3"})
        self.assertAlmostEqual(result.success_rate, 1.0)

    def test_all_failed(self):
        """All pins failed → success_rate == 0.0."""
        result = self._make_result(3, {"a": None, "b": None, "c": None})
        self.assertAlmostEqual(result.success_rate, 0.0)

    def test_partial_success(self):
        """2 of 4 succeeded → success_rate == 0.5."""
        result = self._make_result(4, {"a": "cid1", "b": None, "c": "cid3", "d": None})
        self.assertAlmostEqual(result.success_rate, 0.5)

    def test_empty_registry(self):
        """Empty registry (count=0) → success_rate == 1.0 (no failures = perfect)."""
        result = self._make_result(0, {})
        self.assertAlmostEqual(result.success_rate, 1.0)

    def test_one_of_one_success(self):
        """Single success → success_rate == 1.0."""
        result = self._make_result(1, {"only": "cid"})
        self.assertAlmostEqual(result.success_rate, 1.0)

    def test_one_of_one_failed(self):
        """Single failure → success_rate == 0.0."""
        result = self._make_result(1, {"only": None})
        self.assertAlmostEqual(result.success_rate, 0.0)

    def test_success_rate_complements_total_failed(self):
        """success_rate + failed_rate ≈ 1.0."""
        result = self._make_result(5, {"a": "c", "b": None, "c": "c", "d": None, "e": "c"})
        expected = (5 - result.total_failed) / 5
        self.assertAlmostEqual(result.success_rate, expected)


# ============================================================
# Section 3 — PubSubBus.subscribe() returns ID + unsubscribe_by_id
# ============================================================
class TestPubSubBusSubscribeId(unittest.TestCase):
    """subscribe() returns int ID; unsubscribe_by_id() removes by ID."""

    def setUp(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        self.bus = PubSubBus()

    def test_subscribe_returns_int(self):
        """subscribe() returns an integer subscription ID."""
        sid = self.bus.subscribe("topic.test", lambda t, p: None)
        self.assertIsInstance(sid, int)

    def test_subscribe_ids_are_unique(self):
        """Each subscribe() call returns a distinct ID."""
        sid1 = self.bus.subscribe("t1", lambda t, p: None)
        sid2 = self.bus.subscribe("t2", lambda t, p: None)
        self.assertNotEqual(sid1, sid2)

    def test_subscribe_ids_increment(self):
        """Successive IDs are monotonically increasing."""
        sid1 = self.bus.subscribe("t", lambda t, p: None)
        sid2 = self.bus.subscribe("t", lambda t, p: None)
        self.assertGreater(sid2, sid1)

    def test_unsubscribe_by_id_returns_true(self):
        """unsubscribe_by_id(valid_sid) returns True."""
        sid = self.bus.subscribe("u.topic", lambda t, p: None)
        result = self.bus.unsubscribe_by_id(sid)
        self.assertTrue(result)

    def test_unsubscribe_by_id_removes_handler(self):
        """Handler is not called after unsubscribe_by_id."""
        received = []
        handler = lambda t, p: received.append(p)
        sid = self.bus.subscribe("u2.topic", handler)
        self.bus.unsubscribe_by_id(sid)
        self.bus.publish("u2.topic", {"x": 1})
        self.assertEqual(received, [])

    def test_unsubscribe_by_id_unknown_returns_false(self):
        """unsubscribe_by_id(unknown_sid) returns False."""
        result = self.bus.unsubscribe_by_id(99999)
        self.assertFalse(result)

    def test_unsubscribe_by_id_second_call_returns_false(self):
        """Calling unsubscribe_by_id twice returns False on second call."""
        sid = self.bus.subscribe("u3.topic", lambda t, p: None)
        self.bus.unsubscribe_by_id(sid)
        result = self.bus.unsubscribe_by_id(sid)
        self.assertFalse(result)

    def test_publish_works_after_partial_unsubscribe(self):
        """A second handler still fires after first is removed by ID."""
        received = []
        h1 = lambda t, p: received.append("h1")
        h2 = lambda t, p: received.append("h2")
        sid1 = self.bus.subscribe("partial.topic", h1)
        self.bus.subscribe("partial.topic", h2)
        self.bus.unsubscribe_by_id(sid1)
        self.bus.publish("partial.topic", {})
        self.assertEqual(received, ["h2"])


# ============================================================
# Section 4 — ComplianceChecker.rotate_bak(path, max_keep=3)
# ============================================================
class TestComplianceCheckerRotateBak(unittest.TestCase):
    """ComplianceChecker.rotate_bak() rotates .bak files up to max_keep."""

    def test_rotate_noop_when_no_bak(self):
        """rotate_bak is a no-op when <path>.bak does not exist."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            # Should not raise
            ComplianceChecker.rotate_bak(path)

    def test_rotate_bak_renames_to_bak1(self):
        """Existing .bak is renamed to .bak.1."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            bak = path + ".bak"
            bak1 = path + ".bak.1"
            with open(bak, "w") as f:
                f.write("original")
            ComplianceChecker.rotate_bak(path)
            self.assertFalse(os.path.exists(bak), ".bak should be gone after rotation")
            self.assertTrue(os.path.exists(bak1), ".bak.1 should exist after rotation")
            with open(bak1) as f:
                self.assertEqual(f.read(), "original")

    def test_rotate_shifts_chain(self):
        """.bak moves to .bak.1, .bak.1 moves to .bak.2 on each rotation."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            bak = path + ".bak"
            bak1 = path + ".bak.1"
            bak2 = path + ".bak.2"
            with open(bak, "w") as f:
                f.write("newest")
            with open(bak1, "w") as f:
                f.write("older")
            ComplianceChecker.rotate_bak(path, max_keep=3)
            self.assertFalse(os.path.exists(bak))
            self.assertTrue(os.path.exists(bak1))
            self.assertTrue(os.path.exists(bak2))
            with open(bak1) as f:
                self.assertEqual(f.read(), "newest")
            with open(bak2) as f:
                self.assertEqual(f.read(), "older")

    def test_rotate_evicts_oldest_beyond_max_keep(self):
        """Files beyond max_keep are deleted."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            bak = path + ".bak"
            bak1 = path + ".bak.1"
            bak2 = path + ".bak.2"
            bak3 = path + ".bak.3"
            for p, content in [(bak, "new"), (bak1, "b1"), (bak2, "b2"), (bak3, "b3")]:
                with open(p, "w") as f:
                    f.write(content)
            ComplianceChecker.rotate_bak(path, max_keep=3)
            # .bak.3 (formerly .bak.2 after shift) should exist;
            # original .bak.3 ("b3") should be evicted
            self.assertFalse(os.path.exists(bak))
            self.assertTrue(os.path.exists(bak1))
            self.assertTrue(os.path.exists(bak2))
            self.assertTrue(os.path.exists(bak3))

    def test_rotate_max_keep_one(self):
        """max_keep=1 keeps only .bak.1; rotated content replaces immediately."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            bak = path + ".bak"
            bak1 = path + ".bak.1"
            with open(bak, "w") as f:
                f.write("slot0")
            ComplianceChecker.rotate_bak(path, max_keep=1)
            self.assertFalse(os.path.exists(bak))
            self.assertTrue(os.path.exists(bak1))

    def test_rotate_frees_bak_slot(self):
        """After rotate_bak the .bak slot is free for a new backup."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            bak = path + ".bak"
            with open(bak, "w") as f:
                f.write("old")
            ComplianceChecker.rotate_bak(path)
            self.assertFalse(os.path.exists(bak))
            # Write a new .bak without interference
            with open(bak, "w") as f:
                f.write("new")
            self.assertTrue(os.path.exists(bak))


# ============================================================
# Section 5 — E2E session71
# ============================================================
class TestE2ESession71(unittest.TestCase):
    """End-to-end integration test covering all four Session 71 features."""

    def _make_delegation(self, cid: str):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Delegation, Capability
        cap = Capability(resource="resource:e2e", ability="action/e2e")
        return Delegation(
            cid=cid,
            issuer="did:key:e2e",
            audience="did:key:audience",
            capabilities=[cap],
        )

    def test_merge_result_and_audit_combined(self):
        """MergeResult + audit_log work together."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, MergeResult
        src = DelegationManager()
        src.add(self._make_delegation("bafyE2E001"))
        src.add(self._make_delegation("bafyE2E002"))
        dst = DelegationManager()
        audit = []
        result = dst.merge(src, audit_log=audit)
        self.assertIsInstance(result, MergeResult)
        self.assertEqual(result.added_count, 2)
        self.assertEqual(len(audit), 2)

    def test_subscribe_id_and_unsubscribe(self):
        """subscribe returns ID; unsubscribe_by_id removes handler."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        bus = PubSubBus()
        received = []
        handler = lambda t, p: received.append(p)
        sid = bus.subscribe("e2e.topic", handler)
        self.assertIsInstance(sid, int)
        bus.publish("e2e.topic", {"phase": "before"})
        self.assertEqual(len(received), 1)
        bus.unsubscribe_by_id(sid)
        bus.publish("e2e.topic", {"phase": "after"})
        self.assertEqual(len(received), 1)  # handler is gone

    def test_success_rate_with_partial_failures(self):
        """success_rate reflects partial pin failures."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        r = IPFSReloadResult(count=4, pin_results={"a": "c1", "b": None, "c": "c3", "d": None})
        self.assertAlmostEqual(r.success_rate, 0.5)
        self.assertEqual(r.total_failed, 2)

    def test_rotate_bak_and_bak_path_combined(self):
        """rotate_bak + bak_path work together."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "combined.enc")
            bak = ComplianceChecker.bak_path(path)
            self.assertEqual(bak, path + ".bak")
            with open(bak, "w") as f:
                f.write("initial")
            ComplianceChecker.rotate_bak(path)
            self.assertFalse(os.path.exists(bak))
            self.assertTrue(os.path.exists(path + ".bak.1"))

    def test_all_features_in_single_workflow(self):
        """All four Session 71 features exercised in one workflow."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, MergeResult
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker

        # Feature 1: MergeResult
        src = DelegationManager()
        src.add(self._make_delegation("bafyAll001"))
        dst = DelegationManager()
        merge_result = dst.merge(src)
        self.assertIsInstance(merge_result, MergeResult)
        self.assertEqual(merge_result.added_count, 1)

        # Feature 2: success_rate
        reload_result = IPFSReloadResult(count=2, pin_results={"x": "cid", "y": None})
        self.assertAlmostEqual(reload_result.success_rate, 0.5)

        # Feature 3: subscribe ID + unsubscribe_by_id
        bus = PubSubBus()
        sid = bus.subscribe("all.topic", lambda t, p: None)
        self.assertIsInstance(sid, int)
        self.assertTrue(bus.unsubscribe_by_id(sid))

        # Feature 4: rotate_bak
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "all.enc")
            with open(path + ".bak", "w") as f:
                f.write("backup")
            ComplianceChecker.rotate_bak(path)
            self.assertFalse(ComplianceChecker.bak_exists(path))
            self.assertTrue(os.path.exists(path + ".bak.1"))


if __name__ == "__main__":
    unittest.main()
