"""Session 75 — v30 Next Steps

Tests for:
1. MergeResult.to_dict()                       (ucan_delegation.py)
2. IPFSReloadResult.to_dict()                  (nl_ucan_policy.py)
3. PubSubBus.clear_all()                       (mcp_p2p_transport.py)
4. ComplianceChecker.backup_exists_any(path)   (compliance_checker.py)
5. E2E combined regression                      (all modules)
"""

import json
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
# 1. MergeResult.to_dict()
# ===========================================================================

@unittest.skipUnless(_UCAN_OK, "ucan_delegation not importable")
class TestMergeResultToDict(unittest.TestCase):
    """MergeResult.to_dict() produces a serialisable snapshot."""

    def _result(self, added=0, conflict=0, revocations=0):
        return MergeResult(added_count=added, conflict_count=conflict,
                           revocations_copied=revocations)

    def test_keys_present(self):
        d = self._result().to_dict()
        self.assertIn("added", d)
        self.assertIn("conflicts", d)
        self.assertIn("revocations_copied", d)
        self.assertIn("import_rate", d)

    def test_values_all_added(self):
        d = self._result(added=5).to_dict()
        self.assertEqual(d["added"], 5)
        self.assertEqual(d["conflicts"], 0)
        self.assertEqual(d["revocations_copied"], 0)
        self.assertAlmostEqual(d["import_rate"], 1.0)

    def test_values_mixed(self):
        d = self._result(added=2, conflict=2, revocations=1).to_dict()
        self.assertEqual(d["added"], 2)
        self.assertEqual(d["conflicts"], 2)
        self.assertEqual(d["revocations_copied"], 1)
        self.assertAlmostEqual(d["import_rate"], 0.5)

    def test_zero_total_import_rate_zero(self):
        d = self._result().to_dict()
        self.assertAlmostEqual(d["import_rate"], 0.0)

    def test_is_dict(self):
        self.assertIsInstance(self._result().to_dict(), dict)

    def test_json_serialisable(self):
        d = self._result(added=3, conflict=1, revocations=2).to_dict()
        # Should not raise
        encoded = json.dumps(d)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["added"], 3)
        self.assertEqual(decoded["conflicts"], 1)

    def test_no_extra_keys(self):
        d = self._result().to_dict()
        self.assertEqual(set(d.keys()), {"added", "conflicts", "revocations_copied", "import_rate"})

    def test_via_manager_merge(self):
        cap = Capability(resource="r:dict", ability="a")
        tok = Delegation(cid="cid:dict:1", issuer="a", audience="b", capabilities=[cap])
        src = DelegationManager()
        src.add(tok)
        dst = DelegationManager()
        result = dst.merge(src)
        d = result.to_dict()
        self.assertEqual(d["added"], 1)
        self.assertEqual(d["conflicts"], 0)


# ===========================================================================
# 2. IPFSReloadResult.to_dict()
# ===========================================================================

@unittest.skipUnless(_IPFS_OK, "nl_ucan_policy not importable")
class TestIPFSReloadResultToDict(unittest.TestCase):
    """IPFSReloadResult.to_dict() produces a serialisable snapshot."""

    def _result(self, pin_results, pin_errors=None):
        return IPFSReloadResult(
            count=len(pin_results),
            pin_results=pin_results,
            pin_errors=pin_errors,
        )

    def test_keys_present(self):
        d = self._result({"a": "c"}).to_dict()
        for key in ("count", "succeeded", "failed", "success_rate", "summary"):
            self.assertIn(key, d)

    def test_all_succeeded_values(self):
        d = self._result({"a": "c1", "b": "c2"}).to_dict()
        self.assertEqual(d["count"], 2)
        self.assertEqual(d["succeeded"], 2)
        self.assertEqual(d["failed"], 0)
        self.assertAlmostEqual(d["success_rate"], 1.0)
        self.assertIn("2/2", d["summary"])

    def test_one_failure_values(self):
        d = self._result({"a": "c", "b": None}).to_dict()
        self.assertEqual(d["count"], 2)
        self.assertEqual(d["succeeded"], 1)
        self.assertEqual(d["failed"], 1)
        self.assertAlmostEqual(d["success_rate"], 0.5)
        self.assertIn("1 failed", d["summary"])

    def test_empty_registry(self):
        d = self._result({}).to_dict()
        self.assertEqual(d["count"], 0)
        self.assertEqual(d["succeeded"], 0)
        self.assertEqual(d["failed"], 0)

    def test_is_dict(self):
        self.assertIsInstance(self._result({}).to_dict(), dict)

    def test_json_serialisable(self):
        d = self._result({"p1": "cid", "p2": None}).to_dict()
        encoded = json.dumps(d)
        decoded = json.loads(encoded)
        self.assertEqual(decoded["failed"], 1)

    def test_no_extra_keys(self):
        d = self._result({"x": "cid"}).to_dict()
        self.assertEqual(set(d.keys()), {"count", "succeeded", "failed", "success_rate", "summary"})

    def test_summary_is_string(self):
        d = self._result({"a": "c"}).to_dict()
        self.assertIsInstance(d["summary"], str)


# ===========================================================================
# 3. PubSubBus.clear_all()
# ===========================================================================

@unittest.skipUnless(_PUBSUB_OK, "mcp_p2p_transport not importable")
class TestPubSubBusClearAll(unittest.TestCase):
    """PubSubBus.clear_all() removes every subscriber from every topic."""

    def setUp(self):
        self.bus = PubSubBus()

    def test_clear_all_empty_returns_zero(self):
        self.assertEqual(self.bus.clear_all(), 0)

    def test_clear_all_single_topic(self):
        self.bus.subscribe("t", lambda _t, _p: None)
        n = self.bus.clear_all()
        self.assertEqual(n, 1)

    def test_clear_all_multiple_topics(self):
        self.bus.subscribe("a", lambda _t, _p: None)
        self.bus.subscribe("a", lambda _t, _p: None)
        self.bus.subscribe("b", lambda _t, _p: None)
        n = self.bus.clear_all()
        self.assertEqual(n, 3)

    def test_subscription_count_zero_after_clear_all(self):
        self.bus.subscribe("x", lambda _t, _p: None)
        self.bus.subscribe("y", lambda _t, _p: None)
        self.bus.clear_all()
        self.assertEqual(self.bus.subscription_count(), 0)

    def test_topics_empty_after_clear_all(self):
        self.bus.subscribe("m", lambda _t, _p: None)
        self.bus.clear_all()
        self.assertEqual(self.bus.topics(), [])

    def test_no_events_delivered_after_clear_all(self):
        received = []
        self.bus.subscribe("evt", lambda _t, p: received.append(p))
        self.bus.clear_all()
        self.bus.publish("evt", {"data": 1})
        self.assertEqual(received, [])

    def test_sid_map_empty_after_clear_all(self):
        sid = self.bus.subscribe("q", lambda _t, _p: None)
        self.bus.clear_all()
        # sid no longer valid
        self.assertFalse(self.bus.unsubscribe_by_id(sid))

    def test_double_clear_all_second_returns_zero(self):
        self.bus.subscribe("r", lambda _t, _p: None)
        self.bus.clear_all()
        self.assertEqual(self.bus.clear_all(), 0)

    def test_can_resubscribe_after_clear_all(self):
        received = []
        self.bus.subscribe("s", lambda _t, _p: None)
        self.bus.clear_all()
        self.bus.subscribe("s", lambda _t, p: received.append(p))
        self.bus.publish("s", {"v": 42})
        self.assertEqual(len(received), 1)

    def test_clear_all_returns_correct_count(self):
        for i in range(5):
            self.bus.subscribe(f"topic_{i}", lambda _t, _p: None)
        n = self.bus.clear_all()
        self.assertEqual(n, 5)


# ===========================================================================
# 4. ComplianceChecker.backup_exists_any(path)
# ===========================================================================

@unittest.skipUnless(_COMPLIANCE_OK, "compliance_checker not importable")
class TestComplianceCheckerBackupExistsAny(unittest.TestCase):
    """ComplianceChecker.backup_exists_any() returns bool."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base = os.path.join(self.tmpdir, "rules.enc")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _touch(self, path):
        with open(path, "w") as f:
            f.write("x")

    def test_no_bak_returns_false(self):
        self.assertFalse(ComplianceChecker.backup_exists_any(self.base))

    def test_one_bak_returns_true(self):
        self._touch(self.base + ".bak")
        self.assertTrue(ComplianceChecker.backup_exists_any(self.base))

    def test_numbered_bak_only_returns_true(self):
        self._touch(self.base + ".bak.1")
        # list_bak_files checks .bak first (absent), then .bak.1 (present)
        # but stops only at first gap in *numbered* series, not at .bak absence
        # — so .bak.1 alone IS found, backup_exists_any → True
        self.assertTrue(ComplianceChecker.backup_exists_any(self.base))

    def test_bak_and_numbered_returns_true(self):
        self._touch(self.base + ".bak")
        self._touch(self.base + ".bak.1")
        self.assertTrue(ComplianceChecker.backup_exists_any(self.base))

    def test_returns_bool(self):
        result = ComplianceChecker.backup_exists_any(self.base)
        self.assertIsInstance(result, bool)

    def test_false_after_purge(self):
        self._touch(self.base + ".bak")
        self.assertTrue(ComplianceChecker.backup_exists_any(self.base))
        ComplianceChecker.purge_bak_files(self.base)
        self.assertFalse(ComplianceChecker.backup_exists_any(self.base))

    def test_consistent_with_list_bak_files(self):
        self._touch(self.base + ".bak")
        baks = ComplianceChecker.list_bak_files(self.base)
        self.assertEqual(ComplianceChecker.backup_exists_any(self.base), bool(baks))


# ===========================================================================
# 5. E2E combined regression
# ===========================================================================

@unittest.skipUnless(
    _UCAN_OK and _IPFS_OK and _PUBSUB_OK and _COMPLIANCE_OK,
    "one or more modules not importable",
)
class TestE2ESession75(unittest.TestCase):
    """End-to-end regression covering sessions 71–75."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_merge_result_to_dict_json_round_trip(self):
        cap = Capability(resource="e2e75:r", ability="act")
        tok = Delegation(cid="cid:e2e75:1", issuer="a", audience="b", capabilities=[cap])
        src = DelegationManager()
        src.add(tok)
        dst = DelegationManager()
        result = dst.merge(src)
        encoded = json.dumps(result.to_dict())
        decoded = json.loads(encoded)
        self.assertEqual(decoded["added"], 1)
        self.assertAlmostEqual(decoded["import_rate"], 1.0)

    def test_reload_result_to_dict_json_round_trip(self):
        r = IPFSReloadResult(count=3, pin_results={
            "a": "cid:a", "b": None, "c": "cid:c"
        })
        encoded = json.dumps(r.to_dict())
        decoded = json.loads(encoded)
        self.assertEqual(decoded["count"], 3)
        self.assertEqual(decoded["failed"], 1)
        self.assertAlmostEqual(decoded["success_rate"], 2 / 3)

    def test_clear_all_teardown(self):
        bus = PubSubBus()
        for t in ("t.a", "t.b", "t.c"):
            bus.subscribe(t, lambda _t, _p: None)
        self.assertEqual(bus.subscription_count(), 3)
        n = bus.clear_all()
        self.assertEqual(n, 3)
        self.assertEqual(bus.subscription_count(), 0)
        self.assertEqual(bus.topics(), [])

    def test_backup_exists_any_guards_backup_and_save(self):
        path = os.path.join(self.tmpdir, "e2e75.enc")
        # No backup exists yet
        self.assertFalse(ComplianceChecker.backup_exists_any(path))
        # Write via backup_and_save
        ComplianceChecker.backup_and_save(path, "v1")
        # Still no backup (first write creates the file, no rotation needed)
        self.assertFalse(ComplianceChecker.backup_exists_any(path))
        # Create a .bak manually then check
        with open(path + ".bak", "w") as f:
            f.write("old")
        self.assertTrue(ComplianceChecker.backup_exists_any(path))

    def test_all_session75_features(self):
        """to_dict on both types, clear_all, backup_exists_any in one pass."""
        # MergeResult.to_dict
        r = MergeResult(added_count=4, conflict_count=1, revocations_copied=2)
        d = r.to_dict()
        self.assertEqual(d["added"], 4)
        self.assertAlmostEqual(d["import_rate"], 0.8)

        # IPFSReloadResult.to_dict
        rr = IPFSReloadResult(count=2, pin_results={"x": "c", "y": None})
        dd = rr.to_dict()
        self.assertEqual(dd["failed"], 1)
        self.assertIn("1 failed", dd["summary"])

        # clear_all
        bus = PubSubBus()
        bus.subscribe("s75", lambda _t, _p: None)
        bus.subscribe("s75", lambda _t, _p: None)
        self.assertEqual(bus.clear_all(), 2)

        # backup_exists_any
        base = os.path.join(self.tmpdir, "s75.enc")
        self.assertFalse(ComplianceChecker.backup_exists_any(base))
        with open(base + ".bak", "w") as f:
            f.write("bk")
        self.assertTrue(ComplianceChecker.backup_exists_any(base))


if __name__ == "__main__":
    unittest.main()
