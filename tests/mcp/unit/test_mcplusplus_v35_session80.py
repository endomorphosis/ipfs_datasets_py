"""Session 80 — MCP++ v35 Next Steps.

Implements tests for:
  1. MergeResult.__len__              (returns added_count)
  2. IPFSReloadResult.__len__         (returns count)
  3. PubSubBus.resubscribe(old, new, topic=None)
  4. ComplianceChecker.oldest_backup_path(path)
  5. E2E: len in sum/list comprehensions, resubscribe ordering, targeted purge
"""

from __future__ import annotations

import os
import tempfile

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


def _make_bus():
    from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
    return PubSubBus()


# ---------------------------------------------------------------------------
# 1. MergeResult.__len__
# ---------------------------------------------------------------------------

class TestMergeResultLen:
    def test_len_zero_added(self):
        r = _make_merge_result(added=0)
        assert len(r) == 0

    def test_len_one_added(self):
        r = _make_merge_result(added=1)
        assert len(r) == 1

    def test_len_many_added(self):
        r = _make_merge_result(added=7)
        assert len(r) == 7

    def test_len_added_with_conflicts(self):
        r = _make_merge_result(added=3, conflicts=2)
        assert len(r) == 3

    def test_len_mirrors_int(self):
        r = _make_merge_result(added=5)
        assert len(r) == int(r)

    def test_len_in_sum_comprehension(self):
        results = [_make_merge_result(added=i) for i in range(5)]
        assert sum(len(r) for r in results) == 0 + 1 + 2 + 3 + 4

    def test_len_list_comprehension(self):
        results = [_make_merge_result(added=i) for i in range(1, 4)]
        sizes = [len(r) for r in results]
        assert sizes == [1, 2, 3]

    def test_len_zero_added_conflicts_nonzero(self):
        r = _make_merge_result(added=0, conflicts=10)
        assert len(r) == 0

    def test_len_revocations_not_counted(self):
        r = _make_merge_result(added=2, revocations=5)
        assert len(r) == 2

    def test_len_is_int(self):
        r = _make_merge_result(added=4)
        assert isinstance(len(r), int)


# ---------------------------------------------------------------------------
# 2. IPFSReloadResult.__len__
# ---------------------------------------------------------------------------

class TestIPFSReloadResultLen:
    def test_len_zero_count(self):
        r = _make_reload_result(count=0, failed=0)
        assert len(r) == 0

    def test_len_four_count(self):
        r = _make_reload_result(count=4, failed=0)
        assert len(r) == 4

    def test_len_with_failures(self):
        r = _make_reload_result(count=5, failed=2)
        assert len(r) == 5

    def test_len_all_failed(self):
        r = _make_reload_result(count=3, failed=3)
        assert len(r) == 3

    def test_len_mirrors_count_field(self):
        r = _make_reload_result(count=7, failed=1)
        assert len(r) == r.count

    def test_len_in_sum_comprehension(self):
        results = [_make_reload_result(count=c) for c in [2, 3, 5]]
        assert sum(len(r) for r in results) == 10

    def test_len_is_int(self):
        r = _make_reload_result(count=6)
        assert isinstance(len(r), int)

    def test_len_one_policy(self):
        r = _make_reload_result(count=1, failed=0)
        assert len(r) == 1

    def test_len_large_batch(self):
        r = _make_reload_result(count=100, failed=10)
        assert len(r) == 100

    def test_len_list_comprehension(self):
        results = [_make_reload_result(count=c) for c in range(1, 4)]
        assert [len(r) for r in results] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 3. PubSubBus.resubscribe(old, new, topic=None)
# ---------------------------------------------------------------------------

class TestPubSubBusResubscribe:
    def test_resubscribe_single_topic(self):
        bus = _make_bus()
        old = lambda t, p: None
        new = lambda t, p: None
        bus.subscribe("receipts", old)
        count = bus.resubscribe(old, new, topic="receipts")
        assert count == 1
        hmap = bus.topic_handler_map()
        assert new in hmap["receipts"]
        assert old not in hmap["receipts"]

    def test_resubscribe_across_all_topics(self):
        bus = _make_bus()
        old = lambda t, p: None
        new = lambda t, p: None
        bus.subscribe("receipts", old)
        bus.subscribe("interfaces", old)
        count = bus.resubscribe(old, new)
        assert count == 2
        hmap = bus.topic_handler_map()
        assert new in hmap["receipts"]
        assert new in hmap["interfaces"]
        assert old not in hmap.get("receipts", [])
        assert old not in hmap.get("interfaces", [])

    def test_resubscribe_not_found_returns_zero(self):
        bus = _make_bus()
        old = lambda t, p: None
        new = lambda t, p: None
        count = bus.resubscribe(old, new, topic="receipts")
        assert count == 0

    def test_resubscribe_preserves_other_handlers(self):
        bus = _make_bus()
        other = lambda t, p: None
        old = lambda t, p: None
        new = lambda t, p: None
        bus.subscribe("receipts", other)
        bus.subscribe("receipts", old)
        bus.resubscribe(old, new, topic="receipts")
        hmap = bus.topic_handler_map()
        assert other in hmap["receipts"]
        assert new in hmap["receipts"]

    def test_resubscribe_updates_sid_map(self):
        bus = _make_bus()
        old = lambda t, p: None
        new = lambda t, p: None
        sid = bus.subscribe("receipts", old)
        bus.resubscribe(old, new, topic="receipts")
        # _sid_map stores (topic_key, handler) tuples
        _topic_key, stored_handler = bus._sid_map[sid]
        assert stored_handler is new

    def test_resubscribe_wrong_topic_no_effect(self):
        bus = _make_bus()
        old = lambda t, p: None
        new = lambda t, p: None
        bus.subscribe("receipts", old)
        count = bus.resubscribe(old, new, topic="interfaces")
        assert count == 0
        hmap = bus.topic_handler_map()
        assert old in hmap["receipts"]

    def test_resubscribe_returns_int(self):
        bus = _make_bus()
        old = lambda t, p: None
        new = lambda t, p: None
        result = bus.resubscribe(old, new)
        assert isinstance(result, int)

    def test_resubscribe_new_handler_receives_publish(self):
        bus = _make_bus()
        received = []
        old = lambda t, p: received.append(("old", p))
        new = lambda t, p: received.append(("new", p))
        bus.subscribe("receipts", old)
        bus.resubscribe(old, new, topic="receipts")
        bus.publish("receipts", {"msg": "hello"})
        assert len(received) == 1
        assert received[0][0] == "new"

    def test_resubscribe_topic_none_all_replaced(self):
        bus = _make_bus()
        calls = []
        old = lambda t, p: calls.append("old")
        new = lambda t, p: calls.append("new")
        for topic in ["a", "b", "c"]:
            bus.subscribe(topic, old)
        total = bus.resubscribe(old, new)
        assert total == 3

    def test_resubscribe_idempotent_if_same_handler(self):
        bus = _make_bus()
        h = lambda t, p: None
        bus.subscribe("receipts", h)
        # Replace h with h — should still count as 1 replacement
        count = bus.resubscribe(h, h, topic="receipts")
        assert count == 1


# ---------------------------------------------------------------------------
# 4. ComplianceChecker.oldest_backup_path(path)
# ---------------------------------------------------------------------------

class TestComplianceCheckerOldestBackupPath:
    def test_no_bak_files_returns_none(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "rules.enc")
            assert ComplianceChecker.oldest_backup_path(p) is None

    def test_single_bak_returns_bak(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "rules.enc")
            bak = p + ".bak"
            open(bak, "w").close()
            result = ComplianceChecker.oldest_backup_path(p)
            assert result == bak

    def test_two_bak_returns_bak1(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "rules.enc")
            bak0 = p + ".bak"
            bak1 = p + ".bak.1"
            open(bak0, "w").close()
            open(bak1, "w").close()
            result = ComplianceChecker.oldest_backup_path(p)
            assert result == bak1

    def test_three_bak_returns_bak2(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "rules.enc")
            for suffix in [".bak", ".bak.1", ".bak.2"]:
                open(p + suffix, "w").close()
            result = ComplianceChecker.oldest_backup_path(p)
            assert result == p + ".bak.2"

    def test_complement_of_newest_backup_path_single(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "rules.enc")
            bak = p + ".bak"
            open(bak, "w").close()
            # With only one file, newest == oldest
            assert ComplianceChecker.newest_backup_path(p) == ComplianceChecker.oldest_backup_path(p)

    def test_complement_of_newest_backup_path_multiple(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "rules.enc")
            open(p + ".bak", "w").close()
            open(p + ".bak.1", "w").close()
            newest = ComplianceChecker.newest_backup_path(p)
            oldest = ComplianceChecker.oldest_backup_path(p)
            assert newest != oldest
            assert newest == p + ".bak"
            assert oldest == p + ".bak.1"

    def test_returns_string_or_none(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "rules.enc")
            result = ComplianceChecker.oldest_backup_path(p)
            assert result is None or isinstance(result, str)

    def test_is_static_method(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "rules.enc")
            # Callable without instance
            result = ComplianceChecker.oldest_backup_path(p)
            assert result is None


# ---------------------------------------------------------------------------
# 5. E2E
# ---------------------------------------------------------------------------

class TestE2ESession80:
    def test_len_sum_across_merges(self):
        """sum(len(r) for r in merge_results) gives total added delegations."""
        results = [_make_merge_result(added=i) for i in range(1, 6)]
        total = sum(len(r) for r in results)
        assert total == 1 + 2 + 3 + 4 + 5

    def test_reload_len_equals_count(self):
        """len(IPFSReloadResult) == result.count for a batch reload."""
        r = _make_reload_result(count=8, failed=2)
        assert len(r) == 8
        assert len(r) == r.count

    def test_resubscribe_and_oldest_backup_path(self):
        """resubscribe + oldest_backup_path integration flow."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        bus = _make_bus()
        fired = []
        old_h = lambda t, p: fired.append("old")
        new_h = lambda t, p: fired.append("new")
        bus.subscribe("receipts", old_h)
        n = bus.resubscribe(old_h, new_h, topic="receipts")
        assert n == 1
        bus.publish("receipts", {})
        assert fired == ["new"]

        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "rules.enc")
            open(p + ".bak", "w").close()
            open(p + ".bak.1", "w").close()
            oldest = ComplianceChecker.oldest_backup_path(p)
            assert oldest == p + ".bak.1"
            os.unlink(oldest)
            assert ComplianceChecker.backup_count(p) == 1

    def test_all_four_features_together(self):
        """len, resubscribe, oldest_backup_path work in a combined scenario."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        # MergeResult.__len__
        mr = _make_merge_result(added=3, conflicts=1)
        assert len(mr) == 3
        # IPFSReloadResult.__len__
        rr = _make_reload_result(count=5, failed=1)
        assert len(rr) == 5
        # PubSubBus.resubscribe
        bus = _make_bus()
        calls = []
        oh = lambda t, p: calls.append("old")
        nh = lambda t, p: calls.append("new")
        bus.subscribe("x", oh)
        bus.resubscribe(oh, nh)
        bus.publish("x", {})
        assert calls == ["new"]
        # ComplianceChecker.oldest_backup_path
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "r.enc")
            for s in [".bak", ".bak.1", ".bak.2"]:
                open(p + s, "w").close()
            assert ComplianceChecker.oldest_backup_path(p) == p + ".bak.2"
            assert ComplianceChecker.newest_backup_path(p) == p + ".bak"
