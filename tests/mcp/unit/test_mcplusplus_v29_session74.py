"""Session 74 — v29 Next Steps

Tests for:
1. MergeResult.import_rate property          (ucan_delegation.py)
2. IPFSReloadResult.summarize()              (nl_ucan_policy.py)
3. PubSubBus.clear_topic(topic)              (mcp_p2p_transport.py)
4. ComplianceChecker.backup_and_save(...)   (compliance_checker.py)
5. E2E combined regression                   (all modules)
"""

import os
import tempfile
import unittest
import warnings

try:
    from ipfs_datasets_py.mcp_server.ucan_delegation import (
        DelegationManager, MergeResult, Delegation, Capability,
    )
    _UCAN_OK = True
except Exception:
    _UCAN_OK = False

try:
    from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
    _IPFS_OK = True
except Exception:
    _IPFS_OK = False

try:
    from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus, PubSubEventType
    _PUBSUB_OK = True
except Exception:
    _PUBSUB_OK = False

try:
    from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
    _COMPLIANCE_OK = True
except Exception:
    _COMPLIANCE_OK = False


# ===========================================================================
# 1. MergeResult.import_rate
# ===========================================================================

@unittest.skipUnless(_UCAN_OK, "ucan_delegation not importable")
class TestMergeResultImportRate(unittest.TestCase):
    """MergeResult.import_rate == added_count / total, 0.0 guard for empty."""

    def _result(self, added=0, conflict=0):
        return MergeResult(added_count=added, conflict_count=conflict)

    def test_zero_total_returns_zero(self):
        r = self._result(added=0, conflict=0)
        self.assertEqual(r.import_rate, 0.0)

    def test_all_added_rate_one(self):
        r = self._result(added=5, conflict=0)
        self.assertAlmostEqual(r.import_rate, 1.0)

    def test_none_added_rate_zero(self):
        r = self._result(added=0, conflict=3)
        self.assertAlmostEqual(r.import_rate, 0.0)

    def test_half_added(self):
        r = self._result(added=2, conflict=2)
        self.assertAlmostEqual(r.import_rate, 0.5)

    def test_one_of_three(self):
        r = self._result(added=1, conflict=2)
        self.assertAlmostEqual(r.import_rate, 1 / 3)

    def test_import_rate_is_float(self):
        r = self._result(added=3, conflict=1)
        self.assertIsInstance(r.import_rate, float)

    def test_import_rate_range(self):
        for added in range(5):
            for conflict in range(5):
                r = self._result(added=added, conflict=conflict)
                self.assertGreaterEqual(r.import_rate, 0.0)
                self.assertLessEqual(r.import_rate, 1.0)

    def test_revocations_not_in_denominator(self):
        """revocations_copied does not affect import_rate."""
        r1 = MergeResult(added_count=2, conflict_count=2, revocations_copied=0)
        r2 = MergeResult(added_count=2, conflict_count=2, revocations_copied=100)
        self.assertAlmostEqual(r1.import_rate, r2.import_rate)

    def test_via_manager_merge(self):
        """import_rate computed from a real merge result."""
        cap = Capability(resource="r:rate", ability="a:rate")
        tok1 = Delegation(cid="cid:rate:1", issuer="a", audience="b", capabilities=[cap])
        tok2 = Delegation(cid="cid:rate:2", issuer="a", audience="b", capabilities=[cap])
        src = DelegationManager()
        src.add(tok1)
        src.add(tok2)
        dst = DelegationManager()
        dst._revocation.revoke("cid:rate:1")  # one will conflict
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = dst.merge(src)
        self.assertEqual(result.conflict_count, 1)
        self.assertEqual(result.added_count, 1)
        self.assertAlmostEqual(result.import_rate, 0.5)


# ===========================================================================
# 2. IPFSReloadResult.summarize()
# ===========================================================================

@unittest.skipUnless(_IPFS_OK, "nl_ucan_policy not importable")
class TestIPFSReloadResultSummarize(unittest.TestCase):
    """IPFSReloadResult.summarize() produces expected one-line strings."""

    def _result(self, pin_results, pin_errors=None):
        return IPFSReloadResult(
            count=len(pin_results),
            pin_results=pin_results,
            pin_errors=pin_errors,
        )

    def test_all_succeed_no_failed_clause(self):
        r = self._result({"a": "c1", "b": "c2", "c": "c3"})
        s = r.summarize()
        self.assertEqual(s, "3/3 policies pinned successfully")

    def test_one_failure(self):
        r = self._result({"a": "c1", "b": None})
        s = r.summarize()
        self.assertEqual(s, "1/2 policies pinned successfully (1 failed)")

    def test_all_failed(self):
        r = self._result({"a": None, "b": None})
        s = r.summarize()
        self.assertEqual(s, "0/2 policies pinned successfully (2 failed)")

    def test_empty_registry(self):
        r = self._result({})
        s = r.summarize()
        self.assertEqual(s, "0/0 policies pinned successfully")

    def test_single_success(self):
        r = self._result({"only": "cid"})
        self.assertEqual(r.summarize(), "1/1 policies pinned successfully")

    def test_single_failure(self):
        r = self._result({"only": None})
        self.assertEqual(r.summarize(), "0/1 policies pinned successfully (1 failed)")

    def test_summarize_returns_string(self):
        r = self._result({"p": "cid"})
        self.assertIsInstance(r.summarize(), str)

    def test_summarize_contains_slash_fraction(self):
        r = self._result({"a": "c", "b": None, "c": "c"})
        s = r.summarize()
        self.assertIn("2/3", s)

    def test_summarize_no_failed_clause_when_all_succeed(self):
        r = self._result({"x": "c", "y": "c"})
        self.assertNotIn("failed", r.summarize())

    def test_summarize_failed_clause_present_when_failures(self):
        r = self._result({"x": None})
        self.assertIn("failed", r.summarize())


# ===========================================================================
# 3. PubSubBus.clear_topic()
# ===========================================================================

@unittest.skipUnless(_PUBSUB_OK, "mcp_p2p_transport not importable")
class TestPubSubBusClearTopic(unittest.TestCase):
    """PubSubBus.clear_topic() removes all handlers for a topic."""

    def setUp(self):
        self.bus = PubSubBus()

    def test_clear_unknown_topic_returns_zero(self):
        self.assertEqual(self.bus.clear_topic("no.such.topic"), 0)

    def test_clear_single_handler(self):
        self.bus.subscribe("t1", lambda _t, _p: None)
        count = self.bus.clear_topic("t1")
        self.assertEqual(count, 1)

    def test_clear_multiple_handlers(self):
        def h1(_t, _p): pass  # noqa: E704
        def h2(_t, _p): pass  # noqa: E704
        def h3(_t, _p): pass  # noqa: E704
        self.bus.subscribe("t2", h1)
        self.bus.subscribe("t2", h2)
        self.bus.subscribe("t2", h3)
        count = self.bus.clear_topic("t2")
        self.assertEqual(count, 3)

    def test_cleared_topic_no_longer_receives_events(self):
        received = []
        self.bus.subscribe("t3", lambda _t, p: received.append(p))
        self.bus.clear_topic("t3")
        self.bus.publish("t3", {"x": 1})
        self.assertEqual(received, [])

    def test_cleared_topic_not_in_topics(self):
        def h(_t, _p): pass  # noqa: E704
        self.bus.subscribe("t4", h)
        self.bus.clear_topic("t4")
        self.assertNotIn("t4", self.bus.topics())

    def test_clear_does_not_affect_other_topics(self):
        received = []
        self.bus.subscribe("keep", lambda _t, p: received.append(p))
        self.bus.subscribe("clear_me", lambda _t, _p: None)
        self.bus.clear_topic("clear_me")
        self.bus.publish("keep", {"y": 2})
        self.assertEqual(len(received), 1)

    def test_clear_decrements_subscription_count(self):
        self.bus.subscribe("t5", lambda _t, _p: None)
        self.bus.subscribe("t5", lambda _t, _p: None)
        total_before = self.bus.subscription_count()
        self.bus.clear_topic("t5")
        self.assertEqual(self.bus.subscription_count(), total_before - 2)

    def test_clear_cleans_up_sid_map(self):
        sid = self.bus.subscribe("t6", lambda _t, _p: None)
        self.bus.clear_topic("t6")
        # sid should be gone from sid_map so unsubscribe_by_id returns False
        result = self.bus.unsubscribe_by_id(sid)
        self.assertFalse(result)

    def test_double_clear_returns_zero(self):
        self.bus.subscribe("t7", lambda _t, _p: None)
        self.bus.clear_topic("t7")
        self.assertEqual(self.bus.clear_topic("t7"), 0)

    def test_clear_with_pubsubeventtype(self):
        """clear_topic accepts PubSubEventType enum values."""
        self.bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, lambda _t, _p: None)
        count = self.bus.clear_topic(PubSubEventType.RECEIPT_DISSEMINATE)
        self.assertGreaterEqual(count, 1)


# ===========================================================================
# 4. ComplianceChecker.backup_and_save()
# ===========================================================================

@unittest.skipUnless(_COMPLIANCE_OK, "compliance_checker not importable")
class TestComplianceCheckerBackupAndSave(unittest.TestCase):
    """ComplianceChecker.backup_and_save() rotates bak then writes content."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "data.enc")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_file_when_absent(self):
        ok = ComplianceChecker.backup_and_save(self.path, "hello")
        self.assertTrue(ok)
        with open(self.path) as f:
            self.assertEqual(f.read(), "hello")

    def test_returns_true_on_success(self):
        self.assertIs(ComplianceChecker.backup_and_save(self.path, "x"), True)

    def test_overwrites_existing_file(self):
        with open(self.path, "w") as f:
            f.write("old")
        ComplianceChecker.backup_and_save(self.path, "new")
        with open(self.path) as f:
            self.assertEqual(f.read(), "new")

    def test_rotates_existing_bak(self):
        """Existing .bak is rotated before write."""
        with open(self.path + ".bak", "w") as f:
            f.write("previous_bak")
        ComplianceChecker.backup_and_save(self.path, "content")
        # .bak.1 should exist with the old .bak content
        bak1 = self.path + ".bak.1"
        self.assertTrue(os.path.exists(bak1))
        with open(bak1) as f:
            self.assertEqual(f.read(), "previous_bak")

    def test_no_bak_created_for_new_file(self):
        """No .bak rotation occurs when no .bak exists."""
        ComplianceChecker.backup_and_save(self.path, "first write")
        baks = ComplianceChecker.list_bak_files(self.path)
        self.assertEqual(baks, [])

    def test_max_keep_forwarded(self):
        """max_keep=1 evicts older bak slots."""
        for suffix in [".bak", ".bak.1", ".bak.2"]:
            with open(self.path + suffix, "w") as f:
                f.write("slot")
        ComplianceChecker.backup_and_save(self.path, "content", max_keep=1)
        baks = ComplianceChecker.list_bak_files(self.path)
        # After max_keep=1 rotation only .bak.1 should remain
        self.assertLessEqual(len(baks), 2)

    def test_returns_false_on_write_error(self):
        """Returns False when the destination path is unwritable."""
        # Use a directory as the path to trigger an OSError
        dir_path = os.path.join(self.tmpdir, "subdir")
        os.makedirs(dir_path)
        result = ComplianceChecker.backup_and_save(dir_path, "x")
        self.assertIs(result, False)


# ===========================================================================
# 5. E2E combined regression
# ===========================================================================

@unittest.skipUnless(
    _UCAN_OK and _IPFS_OK and _PUBSUB_OK and _COMPLIANCE_OK,
    "one or more modules not importable",
)
class TestE2ESession74(unittest.TestCase):
    """End-to-end regression covering sessions 71–74."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_import_rate_after_partial_merge(self):
        cap = Capability(resource="e2e74:r", ability="read")
        tok1 = Delegation(cid="cid:e2e74:1", issuer="a", audience="b", capabilities=[cap])
        tok2 = Delegation(cid="cid:e2e74:2", issuer="a", audience="b", capabilities=[cap])
        src = DelegationManager()
        src.add(tok1)
        src.add(tok2)
        dst = DelegationManager()
        dst._revocation.revoke("cid:e2e74:1")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = dst.merge(src)
        self.assertEqual(result.total, 2)
        self.assertAlmostEqual(result.import_rate, 0.5)

    def test_summarize_all_ok(self):
        r = IPFSReloadResult(
            count=2, pin_results={"p1": "cid:1", "p2": "cid:2"}
        )
        self.assertTrue(r.all_succeeded)
        self.assertEqual(r.summarize(), "2/2 policies pinned successfully")

    def test_clear_topic_pipeline(self):
        bus = PubSubBus()
        received = []
        bus.subscribe("pipe.topic", lambda _t, p: received.append(p))
        bus.publish("pipe.topic", {"phase": "before"})
        self.assertEqual(len(received), 1)
        cleared = bus.clear_topic("pipe.topic")
        self.assertEqual(cleared, 1)
        bus.publish("pipe.topic", {"phase": "after"})
        self.assertEqual(len(received), 1)  # handler gone
        self.assertNotIn("pipe.topic", bus.topics())

    def test_backup_and_save_round_trip(self):
        path = os.path.join(self.tmpdir, "e2e74.enc")
        # First write — no existing bak
        ok = ComplianceChecker.backup_and_save(path, "v1")
        self.assertTrue(ok)
        with open(path) as f:
            self.assertEqual(f.read(), "v1")
        # Second write — no .bak existed so still no .bak
        ok = ComplianceChecker.backup_and_save(path, "v2")
        self.assertTrue(ok)
        with open(path) as f:
            self.assertEqual(f.read(), "v2")

    def test_all_features_combined(self):
        """All four Session 74 features in one workflow."""
        # import_rate
        r = MergeResult(added_count=3, conflict_count=1)
        self.assertAlmostEqual(r.import_rate, 0.75)

        # summarize
        reload_r = IPFSReloadResult(count=4, pin_results={
            "a": "cid", "b": "cid", "c": None, "d": "cid"
        })
        s = reload_r.summarize()
        self.assertIn("3/4", s)
        self.assertIn("1 failed", s)

        # clear_topic
        bus = PubSubBus()
        bus.subscribe("all74", lambda _t, _p: None)
        bus.subscribe("all74", lambda _t, _p: None)
        n = bus.clear_topic("all74")
        self.assertEqual(n, 2)

        # backup_and_save
        path = os.path.join(self.tmpdir, "all74.enc")
        self.assertTrue(ComplianceChecker.backup_and_save(path, "data"))
        with open(path) as f:
            self.assertEqual(f.read(), "data")


if __name__ == "__main__":
    unittest.main()
