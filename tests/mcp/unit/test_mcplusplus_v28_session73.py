"""Session 73 — v28 Next Steps

Tests for:
1. MergeResult.total property                   (ucan_delegation.py)
2. IPFSReloadResult.all_succeeded property      (nl_ucan_policy.py)
3. PubSubBus.topics()                           (mcp_p2p_transport.py)
4. ComplianceChecker.purge_bak_files(path)      (compliance_checker.py)
5. E2E combined regression                       (all modules)
"""

import os
import tempfile
import unittest
import warnings

# ---------------------------------------------------------------------------
# Guards — skip whole module if any import fails
# ---------------------------------------------------------------------------
try:
    from ipfs_datasets_py.mcp_server.ucan_delegation import (
        DelegationManager,
        MergeResult,
        Delegation,
        Capability,
    )
    _UCAN_OK = True
except Exception:  # pragma: no cover
    _UCAN_OK = False

try:
    from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
    _IPFS_OK = True
except Exception:  # pragma: no cover
    _IPFS_OK = False

try:
    from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus, PubSubEventType
    _PUBSUB_OK = True
except Exception:  # pragma: no cover
    _PUBSUB_OK = False

try:
    from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
    _COMPLIANCE_OK = True
except Exception:  # pragma: no cover
    _COMPLIANCE_OK = False


# ===========================================================================
# 1. MergeResult.total property
# ===========================================================================

@unittest.skipUnless(_UCAN_OK, "ucan_delegation not importable")
class TestMergeResultTotal(unittest.TestCase):
    """MergeResult.total == added_count + conflict_count."""

    def _result(self, added: int = 0, conflict: int = 0, revocations: int = 0) -> MergeResult:
        return MergeResult(added_count=added, conflict_count=conflict,
                           revocations_copied=revocations)

    def test_total_zeros(self):
        r = self._result()
        self.assertEqual(r.total, 0)

    def test_total_added_only(self):
        r = self._result(added=5)
        self.assertEqual(r.total, 5)

    def test_total_conflict_only(self):
        r = self._result(conflict=3)
        self.assertEqual(r.total, 3)

    def test_total_both(self):
        r = self._result(added=4, conflict=2)
        self.assertEqual(r.total, 6)

    def test_total_revocations_not_counted(self):
        # revocations_copied should NOT be included in total
        r = self._result(added=2, conflict=1, revocations=10)
        self.assertEqual(r.total, 3)

    def test_total_is_int(self):
        r = self._result(added=3, conflict=2)
        self.assertIsInstance(r.total, int)

    def test_import_fraction_all_added(self):
        r = self._result(added=5, conflict=0)
        self.assertEqual(r.total, 5)
        self.assertEqual(r.added_count / r.total, 1.0)

    def test_import_fraction_half(self):
        r = self._result(added=3, conflict=3)
        self.assertAlmostEqual(r.added_count / r.total, 0.5)

    def test_total_zero_guard(self):
        r = self._result(added=0, conflict=0)
        # caller should guard: if result.total: ...
        self.assertEqual(r.total, 0)

    def test_total_large(self):
        r = self._result(added=1000, conflict=999)
        self.assertEqual(r.total, 1999)

    def test_total_via_manager_merge(self):
        mgr_src = DelegationManager()
        cap = Capability(resource="resource:total_test", ability="read")
        tok = Delegation(cid="cid:A", issuer="alice", audience="bob",
                         capabilities=[cap])
        mgr_src.add(tok)
        mgr_dst = DelegationManager()
        result = mgr_dst.merge(mgr_src)
        self.assertEqual(result.total, result.added_count + result.conflict_count)

    def test_total_stable_after_conflict(self):
        cap = Capability(resource="resource:conflict_test", ability="*")
        tok = Delegation(cid="cid:X", issuer="u", audience="v",
                         capabilities=[cap])
        # To generate a conflict, revoke the CID in mgr2 first, then merge
        mgr1 = DelegationManager()
        mgr1.add(tok)
        mgr2 = DelegationManager()
        mgr2._revocation.revoke("cid:X")  # ensures cid:X is treated as conflicted
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = mgr2.merge(mgr1)
        # Revoked CID → conflict_count=1, added_count=0
        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.total, 1)


# ===========================================================================
# 2. IPFSReloadResult.all_succeeded
# ===========================================================================

@unittest.skipUnless(_IPFS_OK, "nl_ucan_policy not importable")
class TestIPFSReloadResultAllSucceeded(unittest.TestCase):
    """IPFSReloadResult.all_succeeded == (total_failed == 0)."""

    def _result(self, pin_results, pin_errors=None):
        return IPFSReloadResult(
            count=len(pin_results),
            pin_results=pin_results,
            pin_errors=pin_errors,
        )

    def test_empty_all_succeeded(self):
        r = self._result({})
        self.assertTrue(r.all_succeeded)

    def test_all_ok_all_succeeded(self):
        r = self._result({"p1": "cid:1", "p2": "cid:2"})
        self.assertTrue(r.all_succeeded)

    def test_one_failure_not_succeeded(self):
        r = self._result({"p1": "cid:1", "p2": None})
        self.assertFalse(r.all_succeeded)

    def test_all_failed_not_succeeded(self):
        r = self._result({"p1": None, "p2": None})
        self.assertFalse(r.all_succeeded)

    def test_all_succeeded_is_bool(self):
        r = self._result({"p1": "cid:1"})
        self.assertIsInstance(r.all_succeeded, bool)

    def test_all_succeeded_mirrors_total_failed(self):
        r = self._result({"a": "c", "b": None})
        self.assertEqual(r.all_succeeded, r.total_failed == 0)

    def test_all_succeeded_true_when_total_failed_zero(self):
        r = self._result({"x": "cid:x"})
        self.assertEqual(r.total_failed, 0)
        self.assertTrue(r.all_succeeded)

    def test_all_succeeded_false_when_total_failed_nonzero(self):
        r = self._result({"x": None})
        self.assertGreater(r.total_failed, 0)
        self.assertFalse(r.all_succeeded)


# ===========================================================================
# 3. PubSubBus.topics()
# ===========================================================================

@unittest.skipUnless(_PUBSUB_OK, "mcp_p2p_transport not importable")
class TestPubSubBusTopics(unittest.TestCase):
    """PubSubBus.topics() returns sorted active topic list."""

    def setUp(self):
        self.bus = PubSubBus()

    def test_topics_empty(self):
        self.assertEqual(self.bus.topics(), [])

    def test_topics_single(self):
        self.bus.subscribe("alpha", lambda _t, _p: None)
        t = self.bus.topics()
        self.assertEqual(t, ["alpha"])

    def test_topics_multiple_sorted(self):
        self.bus.subscribe("zebra", lambda _t, _p: None)
        self.bus.subscribe("apple", lambda _t, _p: None)
        self.bus.subscribe("mango", lambda _t, _p: None)
        t = self.bus.topics()
        self.assertEqual(t, sorted(t))
        self.assertIn("zebra", t)
        self.assertIn("apple", t)
        self.assertIn("mango", t)

    def test_topics_dedup(self):
        h1 = lambda _t, _p: None  # noqa: E731
        h2 = lambda _t, _p: None  # noqa: E731
        self.bus.subscribe("foo", h1)
        self.bus.subscribe("foo", h2)
        t = self.bus.topics()
        self.assertEqual(t.count("foo"), 1)

    def test_topics_is_list(self):
        self.assertIsInstance(self.bus.topics(), list)

    def test_topics_returns_strings(self):
        self.bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, lambda _t, _p: None)
        for item in self.bus.topics():
            self.assertIsInstance(item, str)

    def test_topics_after_unsubscribe_all_removed(self):
        h = lambda _t, _p: None  # noqa: E731
        sid = self.bus.subscribe("tmp", h)
        self.assertIn("tmp", self.bus.topics())
        self.bus.unsubscribe_by_id(sid)
        # topic may still appear with empty handler list; topics() should not
        # return it because we filter v for truthy
        t = self.bus.topics()
        self.assertNotIn("tmp", t)

    def test_topics_consistent_with_subscription_count(self):
        self.bus.subscribe("x", lambda _t, _p: None)
        self.bus.subscribe("y", lambda _t, _p: None)
        t = self.bus.topics()
        self.assertEqual(len(t), 2)
        self.assertGreater(self.bus.subscription_count(), 0)


# ===========================================================================
# 4. ComplianceChecker.purge_bak_files(path)
# ===========================================================================

@unittest.skipUnless(_COMPLIANCE_OK, "compliance_checker not importable")
class TestComplianceCheckerPurgeBakFiles(unittest.TestCase):
    """ComplianceChecker.purge_bak_files() deletes all bak files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base = os.path.join(self.tmpdir, "rules.enc")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _touch(self, path: str) -> None:
        with open(path, "w") as f:
            f.write("x")

    def test_purge_no_bak(self):
        count = ComplianceChecker.purge_bak_files(self.base)
        self.assertEqual(count, 0)

    def test_purge_one_bak(self):
        self._touch(self.base + ".bak")
        count = ComplianceChecker.purge_bak_files(self.base)
        self.assertEqual(count, 1)
        self.assertFalse(os.path.exists(self.base + ".bak"))

    def test_purge_multiple_baks(self):
        for suffix in [".bak", ".bak.1", ".bak.2"]:
            self._touch(self.base + suffix)
        count = ComplianceChecker.purge_bak_files(self.base)
        self.assertEqual(count, 3)
        for suffix in [".bak", ".bak.1", ".bak.2"]:
            self.assertFalse(os.path.exists(self.base + suffix))

    def test_purge_returns_int(self):
        self.assertIsInstance(ComplianceChecker.purge_bak_files(self.base), int)

    def test_purge_idempotent(self):
        self._touch(self.base + ".bak")
        ComplianceChecker.purge_bak_files(self.base)
        count2 = ComplianceChecker.purge_bak_files(self.base)
        self.assertEqual(count2, 0)

    def test_purge_leaves_base_file(self):
        self._touch(self.base)
        self._touch(self.base + ".bak")
        ComplianceChecker.purge_bak_files(self.base)
        self.assertTrue(os.path.exists(self.base))

    def test_purge_after_rotate(self):
        # Create a .bak then rotate to generate .bak and .bak.1
        self._touch(self.base)
        self._touch(self.base + ".bak")
        ComplianceChecker.rotate_bak(self.base)
        baks = ComplianceChecker.list_bak_files(self.base)
        self.assertGreaterEqual(len(baks), 1)
        count = ComplianceChecker.purge_bak_files(self.base)
        self.assertEqual(count, len(baks))
        self.assertEqual(ComplianceChecker.list_bak_files(self.base), [])


# ===========================================================================
# 5. E2E combined regression
# ===========================================================================

@unittest.skipUnless(
    _UCAN_OK and _IPFS_OK and _PUBSUB_OK and _COMPLIANCE_OK,
    "one or more modules not importable",
)
class TestE2ESession73(unittest.TestCase):
    """End-to-end regression covering sessions 69–73."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_merge_result_total_in_pipeline(self):
        """merge() → MergeResult.total includes both added and skipped."""
        cap_r = Capability(resource="resource:e2e73:1", ability="read")
        cap_w = Capability(resource="resource:e2e73:2", ability="write")
        tok1 = Delegation(cid="cid:e2e73:1", issuer="a", audience="b",
                          capabilities=[cap_r])
        tok2 = Delegation(cid="cid:e2e73:2", issuer="a", audience="b",
                          capabilities=[cap_w])
        src = DelegationManager()
        src.add(tok1)
        src.add(tok2)
        dst = DelegationManager()
        # Revoke cid:e2e73:1 in dst so it becomes a merge conflict
        dst._revocation.revoke("cid:e2e73:1")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = dst.merge(src)
        self.assertEqual(result.total, result.added_count + result.conflict_count)
        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.added_count, 1)
        self.assertEqual(result.total, 2)

    def test_reload_result_all_succeeded_and_total(self):
        """IPFSReloadResult with mixed results exercises all_succeeded + total."""
        r_good = IPFSReloadResult(
            count=2, pin_results={"a": "cid:a", "b": "cid:b"}
        )
        self.assertTrue(r_good.all_succeeded)
        r_bad = IPFSReloadResult(
            count=2, pin_results={"a": "cid:a", "b": None},
            pin_errors={"b": "timeout"},
        )
        self.assertFalse(r_bad.all_succeeded)
        self.assertEqual(r_bad.failure_details, {"b": "timeout"})

    def test_pubsub_topics_lifecycle(self):
        """subscribe → topics() lists topic; unsubscribe_by_id → gone."""
        bus = PubSubBus()
        self.assertEqual(bus.topics(), [])
        sid = bus.subscribe("tpc:alpha", lambda _t, _p: None)
        self.assertIn("tpc:alpha", bus.topics())
        bus.unsubscribe_by_id(sid)
        self.assertNotIn("tpc:alpha", bus.topics())

    def test_purge_bak_after_compliance_rotate(self):
        """rotate_bak creates backups; purge_bak_files removes them all."""
        base = os.path.join(self.tmpdir, "check.enc")
        with open(base + ".bak", "w") as f:
            f.write("old")
        with open(base, "w") as f:
            f.write("current")
        ComplianceChecker.rotate_bak(base)
        baks = ComplianceChecker.list_bak_files(base)
        self.assertGreaterEqual(len(baks), 1)
        removed = ComplianceChecker.purge_bak_files(base)
        self.assertEqual(removed, len(baks))
        self.assertEqual(ComplianceChecker.list_bak_files(base), [])


if __name__ == "__main__":
    unittest.main()
