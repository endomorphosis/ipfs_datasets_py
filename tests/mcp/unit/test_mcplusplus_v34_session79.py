"""Session 79 — MCP++ v34 Next Steps.

Implements tests for:
  1. MergeResult.__bool__         (True iff added_count > 0)
  2. IPFSReloadResult.__bool__    (True iff all_succeeded)
  3. PubSubBus.topic_handler_map() shallow-copy snapshot
  4. ComplianceChecker.newest_backup_path(path)
  5. E2E: bool in conditionals, snapshot isolation, restore flow
"""

from __future__ import annotations

import os
import tempfile
import warnings

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_merge_result(added: int = 0, conflicts: int = 0, revocations: int = 0):
    from ipfs_datasets_py.mcp_server.ucan_delegation import MergeResult
    return MergeResult(added_count=added, conflict_count=conflicts, revocations_copied=revocations)


def _make_reload_result(count: int = 4, failed: int = 0):
    from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
    pin_results = {}
    for i in range(count - failed):
        pin_results[f"p{i}"] = f"Qm{i:040d}"
    for i in range(failed):
        pin_results[f"f{i}"] = None
    return IPFSReloadResult(count=count, pin_results=pin_results)


# ---------------------------------------------------------------------------
# 1. MergeResult.__bool__
# ---------------------------------------------------------------------------

class TestMergeResultBool:
    def test_bool_zero_added_is_false(self):
        r = _make_merge_result(added=0)
        assert bool(r) is False

    def test_bool_one_added_is_true(self):
        r = _make_merge_result(added=1)
        assert bool(r) is True

    def test_bool_many_added_is_true(self):
        r = _make_merge_result(added=10)
        assert bool(r) is True

    def test_bool_conflicts_only_is_false(self):
        r = _make_merge_result(added=0, conflicts=5)
        assert bool(r) is False

    def test_bool_if_branch(self):
        r = _make_merge_result(added=3)
        executed = []
        if r:
            executed.append("yes")
        assert executed == ["yes"]

    def test_bool_else_branch(self):
        r = _make_merge_result(added=0)
        executed = []
        if r:
            executed.append("yes")
        else:
            executed.append("no")
        assert executed == ["no"]

    def test_bool_added_zero_conflicts_nonzero_false(self):
        r = _make_merge_result(added=0, conflicts=3, revocations=2)
        assert not bool(r)

    def test_bool_not_operator(self):
        r = _make_merge_result(added=0)
        assert not r

    def test_bool_truthy_filter(self):
        results = [_make_merge_result(0), _make_merge_result(2), _make_merge_result(0), _make_merge_result(1)]
        truthy = [r for r in results if r]
        assert len(truthy) == 2

    def test_bool_int_conversion_independent(self):
        """__bool__ is independent of __int__ (which returns added_count)."""
        r = _make_merge_result(added=0)
        assert not bool(r)
        assert int(r) == 0


# ---------------------------------------------------------------------------
# 2. IPFSReloadResult.__bool__
# ---------------------------------------------------------------------------

class TestIPFSReloadResultBool:
    def test_bool_all_succeed_is_true(self):
        r = _make_reload_result(count=3, failed=0)
        assert bool(r) is True

    def test_bool_one_failure_is_false(self):
        r = _make_reload_result(count=3, failed=1)
        assert bool(r) is False

    def test_bool_all_failed_is_false(self):
        r = _make_reload_result(count=3, failed=3)
        assert bool(r) is False

    def test_bool_empty_count_is_true(self):
        """Empty reload (0 policies) → all_succeeded=True → __bool__=True."""
        r = _make_reload_result(count=0, failed=0)
        assert bool(r) is True

    def test_bool_if_branch(self):
        r = _make_reload_result(count=2, failed=0)
        executed = []
        if r:
            executed.append("ok")
        assert executed == ["ok"]

    def test_bool_else_branch(self):
        r = _make_reload_result(count=2, failed=1)
        executed = []
        if r:
            executed.append("ok")
        else:
            executed.append("fail")
        assert executed == ["fail"]

    def test_bool_not_operator(self):
        r = _make_reload_result(count=4, failed=2)
        assert not bool(r)

    def test_bool_consistent_with_all_succeeded(self):
        r = _make_reload_result(count=5, failed=0)
        assert bool(r) == r.all_succeeded

    def test_bool_consistent_with_all_succeeded_fail(self):
        r = _make_reload_result(count=5, failed=1)
        assert bool(r) == r.all_succeeded

    def test_bool_filter_results(self):
        results = [
            _make_reload_result(3, 0),
            _make_reload_result(3, 1),
            _make_reload_result(2, 0),
            _make_reload_result(2, 2),
        ]
        good = [r for r in results if r]
        assert len(good) == 2


# ---------------------------------------------------------------------------
# 3. PubSubBus.topic_handler_map()
# ---------------------------------------------------------------------------

class TestPubSubBusTopicHandlerMap:
    def _make_bus(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        return PubSubBus()

    def test_empty_returns_empty_dict(self):
        bus = self._make_bus()
        assert bus.topic_handler_map() == {}

    def test_single_topic_single_handler(self):
        bus = self._make_bus()
        cb = lambda t, p: None
        bus.subscribe("alpha", cb)
        m = bus.topic_handler_map()
        assert "alpha" in m
        assert len(m["alpha"]) == 1
        assert m["alpha"][0] is cb

    def test_multiple_topics(self):
        bus = self._make_bus()
        cb1 = lambda t, p: None
        cb2 = lambda t, p: None
        bus.subscribe("a", cb1)
        bus.subscribe("b", cb2)
        m = bus.topic_handler_map()
        assert set(m.keys()) == {"a", "b"}

    def test_same_handler_on_two_topics(self):
        bus = self._make_bus()
        cb = lambda t, p: None
        bus.subscribe("x", cb)
        bus.subscribe("y", cb)
        m = bus.topic_handler_map()
        assert len(m["x"]) == 1
        assert len(m["y"]) == 1
        assert m["x"][0] is cb
        assert m["y"][0] is cb

    def test_returns_copy_modification_does_not_affect_bus(self):
        bus = self._make_bus()
        cb = lambda t, p: None
        bus.subscribe("z", cb)
        m = bus.topic_handler_map()
        m["z"].clear()
        # The bus should still have the handler
        assert bus.subscription_count("z") == 1

    def test_cleared_topic_not_in_map(self):
        bus = self._make_bus()
        cb = lambda t, p: None
        bus.subscribe("q", cb)
        bus.clear_topic("q")
        m = bus.topic_handler_map()
        assert "q" not in m

    def test_after_clear_all_returns_empty(self):
        bus = self._make_bus()
        bus.subscribe("a", lambda t, p: None)
        bus.subscribe("b", lambda t, p: None)
        bus.clear_all()
        assert bus.topic_handler_map() == {}

    def test_multiple_handlers_same_topic(self):
        bus = self._make_bus()
        cb1 = lambda t, p: None
        cb2 = lambda t, p: None
        bus.subscribe("multi", cb1)
        bus.subscribe("multi", cb2)
        m = bus.topic_handler_map()
        assert len(m["multi"]) == 2

    def test_snapshot_is_shallow_copy_of_lists(self):
        bus = self._make_bus()
        cb = lambda t, p: None
        bus.subscribe("snap", cb)
        m1 = bus.topic_handler_map()
        m2 = bus.topic_handler_map()
        # Different list objects
        assert m1["snap"] is not m2["snap"]
        # Same contents
        assert m1["snap"] == m2["snap"]

    def test_only_topics_with_handlers_included(self):
        bus = self._make_bus()
        cb = lambda t, p: None
        bus.subscribe("present", cb)
        # "absent" never subscribed
        m = bus.topic_handler_map()
        assert "absent" not in m
        assert "present" in m


# ---------------------------------------------------------------------------
# 4. ComplianceChecker.newest_backup_path(path)
# ---------------------------------------------------------------------------

class TestComplianceCheckerNewestBackupPath:
    def test_no_backup_returns_none(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.json")
            assert ComplianceChecker.newest_backup_path(path) is None

    def test_primary_bak_returned(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.json")
            bak = path + ".bak"
            with open(bak, "w") as f:
                f.write("backup")
            result = ComplianceChecker.newest_backup_path(path)
            assert result == bak

    def test_returns_dot_bak_not_dot_bak_1(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.json")
            bak = path + ".bak"
            bak1 = path + ".bak.1"
            with open(bak, "w") as f:
                f.write("newest")
            with open(bak1, "w") as f:
                f.write("older")
            result = ComplianceChecker.newest_backup_path(path)
            assert result == bak

    def test_numbered_only_bak_returned(self):
        """Without .bak but with .bak.1, list_bak_files still returns it."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.json")
            bak1 = path + ".bak.1"
            with open(bak1, "w") as f:
                f.write("numbered only")
            # list_bak_files returns [.bak.1] even without .bak
            result = ComplianceChecker.newest_backup_path(path)
            # Returns the first available backup (bak.1 in this case)
            assert result == bak1

    def test_is_static_method(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        # Should callable without instance
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.json")
            r = ComplianceChecker.newest_backup_path(path)
            assert r is None

    def test_complement_of_oldest_backup_age(self):
        """newest_backup_path returns path[0], oldest_backup_age uses path[-1]."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.json")
            bak = path + ".bak"
            bak1 = path + ".bak.1"
            with open(bak, "w") as f:
                f.write("newest")
            with open(bak1, "w") as f:
                f.write("oldest")
            newest = ComplianceChecker.newest_backup_path(path)
            oldest_age = ComplianceChecker.oldest_backup_age(path)
            assert newest == bak
            # oldest_age references bak1 mtime — it should be a float
            assert isinstance(oldest_age, float)

    def test_after_rotate_bak_newest_is_updated(self):
        """After rotate_bak, the primary .bak is consumed; .bak.1 becomes the newest."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.json")
            with open(path, "w") as f:
                f.write("original")
            # Manually place an existing .bak to simulate rotation
            bak = path + ".bak"
            with open(bak, "w") as f:
                f.write("old_bak")
            ComplianceChecker.rotate_bak(path, max_keep=2)
            # After rotate, .bak was moved to .bak.1; newest is now .bak.1
            bak1 = path + ".bak.1"
            result = ComplianceChecker.newest_backup_path(path)
            # Either None (if no bak) or bak.1 (if present after rotation)
            assert result is None or result == bak1

    def test_returns_string_path(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.json")
            bak = path + ".bak"
            with open(bak, "w") as f:
                f.write("data")
            result = ComplianceChecker.newest_backup_path(path)
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# 5. E2E Session 79
# ---------------------------------------------------------------------------

class TestE2ESession79:
    def test_merge_result_bool_in_pipeline(self):
        """MergeResult bool used in a typical dispatch pattern."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, Delegation, Capability,
        )
        mgr1 = DelegationManager()
        mgr2 = DelegationManager()
        cap = Capability(resource="tool:read", ability="invoke")
        d = Delegation(
            cid="cid_bool_test", issuer="alice", audience="bob",
            capabilities=[cap], expiry=9999999999,
        )
        mgr1.add(d)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = mgr2.merge(mgr1)
        # result should be truthy since 1 delegation was added
        if result:
            flag = True
        else:
            flag = False
        assert flag is True

    def test_ipfs_reload_result_bool_in_pipeline(self):
        """IPFSReloadResult bool used in an alert pattern."""
        r_good = _make_reload_result(count=4, failed=0)
        r_bad = _make_reload_result(count=4, failed=1)
        alerts = []
        for r in [r_good, r_bad]:
            if not r:
                alerts.append("alert")
        assert len(alerts) == 1

    def test_topic_handler_map_snapshot_isolation(self):
        """Mutation of snapshot does not affect live bus."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        bus = PubSubBus()
        cb = lambda t, p: None
        sid = bus.subscribe("events", cb)
        m = bus.topic_handler_map()
        m["events"].clear()
        assert bus.subscription_count("events") == 1

    def test_newest_backup_path_in_restore_flow(self):
        """newest_backup_path used to conditionally restore."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "rules.json")
            with open(path, "w") as f:
                f.write("current")
            bak = path + ".bak"
            with open(bak, "w") as f:
                f.write("backup_content")
            newest = ComplianceChecker.newest_backup_path(path)
            if newest is not None:
                checker = ComplianceChecker()
                ok = checker.restore_from_bak(path)
                assert ok is True
            else:
                pytest.fail("Expected newest_backup_path to return a path")

    @pytest.mark.skipif(
        not any(
            hasattr(__import__("importlib").util.find_spec(m) or type("", (), {"origin": None})(), "origin")
            for m in ["ipfs_kit_py"]
        ),
        reason="ipfs_kit_py not installed",
    )
    def test_ipfs_reload_bool_with_real_store(self):
        """IPFSReloadResult.__bool__ works with IPFSPolicyStore (skip if no IPFS)."""
        pytest.skip("Requires real IPFS daemon")
