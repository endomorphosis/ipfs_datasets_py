"""
Session 72 tests — MCP++ v27 Next Steps
========================================
Items tested:
1. MergeResult rich comparison operators (__lt__, __le__, __gt__, __ge__)
2. IPFSReloadResult.failure_details property + pin_errors NamedTuple field
3. PubSubBus.subscription_count(topic=None)
4. ComplianceChecker.list_bak_files(path)
5. E2E covering all four features together
"""

import os
import sys
import tempfile
import unittest

# ---------------------------------------------------------------------------
# Repository root on PYTHONPATH
# ---------------------------------------------------------------------------
_REPO_ROOT = __file__
for _ in range(4):
    _REPO_ROOT = os.path.dirname(_REPO_ROOT)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ============================================================
# Section 1 — MergeResult rich comparison operators
# ============================================================
class TestMergeResultRichComparison(unittest.TestCase):
    """MergeResult supports <, <=, >, >= comparisons against int and MergeResult."""

    def _result(self, n: int):
        from ipfs_datasets_py.mcp_server.ucan_delegation import MergeResult
        return MergeResult(added_count=n)

    # --- comparisons against int ---

    def test_lt_int_true(self):
        self.assertTrue(self._result(1) < 2)

    def test_lt_int_false(self):
        self.assertFalse(self._result(2) < 2)

    def test_le_int_equal(self):
        self.assertTrue(self._result(2) <= 2)

    def test_le_int_less(self):
        self.assertTrue(self._result(1) <= 2)

    def test_le_int_false(self):
        self.assertFalse(self._result(3) <= 2)

    def test_gt_int_true(self):
        self.assertTrue(self._result(3) > 2)

    def test_gt_int_false(self):
        self.assertFalse(self._result(1) > 2)

    def test_ge_int_equal(self):
        self.assertTrue(self._result(2) >= 2)

    def test_ge_int_greater(self):
        self.assertTrue(self._result(3) >= 2)

    def test_ge_int_false(self):
        self.assertFalse(self._result(1) >= 2)

    # --- comparisons against MergeResult ---

    def test_lt_merge_result(self):
        self.assertTrue(self._result(1) < self._result(2))

    def test_gt_merge_result(self):
        self.assertTrue(self._result(3) > self._result(2))

    def test_le_merge_result_equal(self):
        self.assertTrue(self._result(2) <= self._result(2))

    def test_ge_merge_result_equal(self):
        self.assertTrue(self._result(2) >= self._result(2))

    # --- existing backward-compat still works ---

    def test_eq_int_still_works(self):
        self.assertEqual(self._result(5), 5)

    def test_int_cast_still_works(self):
        self.assertEqual(int(self._result(7)), 7)

    def test_assert_ge_1_pattern(self):
        """Common use: assert result >= 1 after a successful merge."""
        result = self._result(3)
        self.assertGreaterEqual(result, 1)
        self.assertGreaterEqual(result, 3)
        self.assertFalse(result >= 4)


# ============================================================
# Section 2 — IPFSReloadResult.failure_details
# ============================================================
class TestIPFSReloadResultFailureDetails(unittest.TestCase):
    """IPFSReloadResult.failure_details combines pin_errors with fallback."""

    def _make(self, count, pin_results, pin_errors=None):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        return IPFSReloadResult(count=count, pin_results=pin_results, pin_errors=pin_errors)

    def test_no_failures_empty_dict(self):
        """failure_details is {} when all pins succeeded."""
        r = self._make(2, {"a": "cid1", "b": "cid2"})
        self.assertEqual(r.failure_details, {})

    def test_failure_with_error_in_pin_errors(self):
        """Known error message surfaced from pin_errors."""
        r = self._make(2, {"a": "cid1", "b": None}, pin_errors={"b": "IPFS timeout"})
        details = r.failure_details
        self.assertIn("b", details)
        self.assertEqual(details["b"], "IPFS timeout")
        self.assertNotIn("a", details)

    def test_failure_without_pin_errors_uses_fallback(self):
        """Unknown failure gets 'unknown error' fallback."""
        r = self._make(2, {"a": None, "b": "cid2"})
        details = r.failure_details
        self.assertIn("a", details)
        self.assertEqual(details["a"], "unknown error")

    def test_partial_pin_errors_fallback_for_missing(self):
        """pin_errors has entry for one failure but not another."""
        r = self._make(
            3,
            {"a": None, "b": None, "c": "cid3"},
            pin_errors={"a": "connection refused"},
        )
        details = r.failure_details
        self.assertEqual(details["a"], "connection refused")
        self.assertEqual(details["b"], "unknown error")
        self.assertNotIn("c", details)

    def test_pin_errors_none_default(self):
        """Default pin_errors=None works (no KeyError)."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        r = IPFSReloadResult(count=1, pin_results={"x": None})
        self.assertEqual(r.failure_details, {"x": "unknown error"})

    def test_all_failed_with_errors(self):
        """All policies failed, all errors documented."""
        r = self._make(
            2,
            {"p": None, "q": None},
            pin_errors={"p": "err1", "q": "err2"},
        )
        self.assertEqual(r.failure_details, {"p": "err1", "q": "err2"})

    def test_empty_registry(self):
        """Empty registry yields empty failure_details."""
        r = self._make(0, {})
        self.assertEqual(r.failure_details, {})

    def test_failure_details_count_matches_total_failed(self):
        """len(failure_details) == total_failed."""
        r = self._make(4, {"a": "c", "b": None, "c": None, "d": "c"})
        self.assertEqual(len(r.failure_details), r.total_failed)


# ============================================================
# Section 3 — PubSubBus.subscription_count(topic=None)
# ============================================================
class TestPubSubBusSubscriptionCount(unittest.TestCase):
    """subscription_count returns total active subscriptions."""

    def setUp(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        self.bus = PubSubBus()

    def test_empty_bus_count_zero(self):
        """Fresh bus has no subscriptions."""
        self.assertEqual(self.bus.subscription_count(), 0)

    def test_single_topic_count(self):
        """One handler on one topic."""
        self.bus.subscribe("t1", lambda t, p: None)
        self.assertEqual(self.bus.subscription_count(), 1)

    def test_multi_topic_total(self):
        """Handlers across topics are summed."""
        self.bus.subscribe("t1", lambda t, p: None)
        self.bus.subscribe("t2", lambda t, p: None)
        self.bus.subscribe("t3", lambda t, p: None)
        self.assertEqual(self.bus.subscription_count(), 3)

    def test_topic_filter(self):
        """topic= filters to a specific topic."""
        self.bus.subscribe("t1", lambda t, p: None)
        self.bus.subscribe("t2", lambda t, p: None)
        self.assertEqual(self.bus.subscription_count("t1"), 1)
        self.assertEqual(self.bus.subscription_count("t2"), 1)

    def test_unknown_topic_returns_zero(self):
        """topic= for unknown topic returns 0."""
        self.assertEqual(self.bus.subscription_count("no.such.topic"), 0)

    def test_count_decreases_after_unsubscribe(self):
        """Removing a handler reduces count."""
        h = lambda t, p: None
        self.bus.subscribe("t1", h)
        self.assertEqual(self.bus.subscription_count(), 1)
        self.bus.unsubscribe("t1", h)
        self.assertEqual(self.bus.subscription_count(), 0)

    def test_count_decreases_after_unsubscribe_by_id(self):
        """unsubscribe_by_id also decrements count."""
        sid = self.bus.subscribe("t1", lambda t, p: None)
        self.assertEqual(self.bus.subscription_count(), 1)
        self.bus.unsubscribe_by_id(sid)
        self.assertEqual(self.bus.subscription_count(), 0)

    def test_duplicate_handler_not_double_counted(self):
        """Same handler registered twice on same topic counts once."""
        h = lambda t, p: None
        self.bus.subscribe("t1", h)
        self.bus.subscribe("t1", h)  # duplicate — ignored
        self.assertEqual(self.bus.subscription_count("t1"), 1)


# ============================================================
# Section 4 — ComplianceChecker.list_bak_files(path)
# ============================================================
class TestComplianceCheckerListBakFiles(unittest.TestCase):
    """list_bak_files returns sorted list of existing backup paths."""

    def test_no_backups_empty_list(self):
        """Returns [] when no .bak files exist."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            self.assertEqual(ComplianceChecker.list_bak_files(path), [])

    def test_only_bak_exists(self):
        """Returns [<path>.bak] when only base backup exists."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            bak = path + ".bak"
            open(bak, "w").close()
            result = ComplianceChecker.list_bak_files(path)
            self.assertEqual(result, [bak])

    def test_bak_and_numbered_listed(self):
        """Returns .bak, .bak.1, .bak.2 when all exist."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            bak = path + ".bak"
            bak1 = path + ".bak.1"
            bak2 = path + ".bak.2"
            for p in [bak, bak1, bak2]:
                open(p, "w").close()
            result = ComplianceChecker.list_bak_files(path)
            self.assertEqual(result, [bak, bak1, bak2])

    def test_stops_at_gap(self):
        """Stops listing when a numbered slot is missing (.bak.1 absent stops before .bak.2)."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            bak = path + ".bak"
            bak2 = path + ".bak.2"
            open(bak, "w").close()
            open(bak2, "w").close()  # gap at .bak.1
            result = ComplianceChecker.list_bak_files(path)
            # Should return [bak] only — stops when .bak.1 is absent
            self.assertEqual(result, [bak])

    def test_after_rotate_bak(self):
        """list_bak_files reflects the state after rotate_bak."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.enc")
            bak = path + ".bak"
            with open(bak, "w") as f:
                f.write("backup")
            ComplianceChecker.rotate_bak(path)
            result = ComplianceChecker.list_bak_files(path)
            # After rotation, .bak is gone and .bak.1 exists
            self.assertNotIn(bak, result)
            self.assertIn(path + ".bak.1", result)


# ============================================================
# Section 5 — E2E Session 72
# ============================================================
class TestE2ESession72(unittest.TestCase):
    """End-to-end integration test covering all four Session 72 features."""

    def _make_delegation(self, cid: str):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Delegation, Capability
        cap = Capability(resource="resource:e2e72", ability="action/e2e72")
        return Delegation(
            cid=cid,
            issuer="did:key:e2e72",
            audience="did:key:audience72",
            capabilities=[cap],
        )

    def test_merge_result_ordering(self):
        """MergeResult rich comparison in a realistic merge scenario."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        src.add(self._make_delegation("bafyE72a"))
        src.add(self._make_delegation("bafyE72b"))
        dst = DelegationManager()
        result = dst.merge(src)
        self.assertGreaterEqual(result, 1)
        self.assertGreater(result, 0)
        self.assertLess(result, 100)

    def test_failure_details_with_pin_errors(self):
        """failure_details exposes per-policy error reasons."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        r = IPFSReloadResult(
            count=3,
            pin_results={"pol_a": "cid1", "pol_b": None, "pol_c": None},
            pin_errors={"pol_b": "connection timeout"},
        )
        details = r.failure_details
        self.assertEqual(details["pol_b"], "connection timeout")
        self.assertEqual(details["pol_c"], "unknown error")
        self.assertNotIn("pol_a", details)
        self.assertAlmostEqual(r.success_rate, 1 / 3)

    def test_subscription_count_across_topics(self):
        """subscription_count tracks handlers across subscribe/unsubscribe."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        bus = PubSubBus()
        sid1 = bus.subscribe("receipts", lambda t, p: None)
        sid2 = bus.subscribe("alerts", lambda t, p: None)
        self.assertEqual(bus.subscription_count(), 2)
        self.assertEqual(bus.subscription_count("receipts"), 1)
        bus.unsubscribe_by_id(sid1)
        self.assertEqual(bus.subscription_count(), 1)
        bus.unsubscribe_by_id(sid2)
        self.assertEqual(bus.subscription_count(), 0)

    def test_list_bak_files_and_rotate_combined(self):
        """list_bak_files reflects rotation history."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "combined.enc")
            # No backups yet
            self.assertEqual(ComplianceChecker.list_bak_files(path), [])
            # Create .bak
            with open(path + ".bak", "w") as f:
                f.write("v1")
            self.assertEqual(len(ComplianceChecker.list_bak_files(path)), 1)
            # Rotate → .bak freed, .bak.1 created
            ComplianceChecker.rotate_bak(path)
            files = ComplianceChecker.list_bak_files(path)
            self.assertEqual(files, [path + ".bak.1"])

    def test_all_features_in_single_workflow(self):
        """All four Session 72 features exercised in one workflow."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager, MergeResult
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker

        # Feature 1: rich comparison
        src = DelegationManager()
        src.add(self._make_delegation("bafyAll72a"))
        dst = DelegationManager()
        result = dst.merge(src)
        self.assertIsInstance(result, MergeResult)
        self.assertGreaterEqual(result, 1)

        # Feature 2: failure_details
        reload_result = IPFSReloadResult(
            count=2,
            pin_results={"x": "cid", "y": None},
            pin_errors={"y": "timeout"},
        )
        self.assertEqual(reload_result.failure_details["y"], "timeout")

        # Feature 3: subscription_count
        bus = PubSubBus()
        bus.subscribe("all72.t1", lambda t, p: None)
        bus.subscribe("all72.t2", lambda t, p: None)
        self.assertEqual(bus.subscription_count(), 2)

        # Feature 4: list_bak_files
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "all72.enc")
            self.assertEqual(ComplianceChecker.list_bak_files(path), [])
            open(path + ".bak", "w").close()
            self.assertEqual(len(ComplianceChecker.list_bak_files(path)), 1)


if __name__ == "__main__":
    unittest.main()
