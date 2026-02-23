"""Session 82 — MCP++ v37 Next Steps.

Implements tests for:
  1. MergeResult.keys()                      (list of field names)
  2. IPFSReloadResult.iter_succeeded()       (generator of (name, cid) pairs)
  3. PubSubBus.topic_sid_map()               ({topic: sorted_sid_list})
  4. ComplianceChecker.backup_names(path)    (basenames of backup files)
  5. E2E: keys() round-trip, iter_succeeded filtering,
          topic_sid_map consistency, backup_names purge cycle
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


def _make_reload_result(count: int = 4, failed: int = 0,
                        pin_errors: dict | None = None):
    from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
    pin_results: dict = {}
    for i in range(count - failed):
        pin_results[f"p{i}"] = f"Qm{i:040d}"
    for i in range(failed):
        pin_results[f"f{i}"] = None
    return IPFSReloadResult(count=count, pin_results=pin_results,
                            pin_errors=pin_errors)


def _make_bus():
    from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
    return PubSubBus()


# ---------------------------------------------------------------------------
# 1. MergeResult.keys()
# ---------------------------------------------------------------------------

class TestMergeResultKeys:
    def test_keys_returns_list(self):
        r = _make_merge_result()
        assert isinstance(r.keys(), list)

    def test_keys_length_three(self):
        r = _make_merge_result()
        assert len(r.keys()) == 3

    def test_keys_content(self):
        r = _make_merge_result()
        assert r.keys() == ["added_count", "conflict_count", "revocations_copied"]

    def test_keys_stable_order(self):
        r1 = _make_merge_result(added=1, conflicts=2, revocations=3)
        r2 = _make_merge_result(added=9, conflicts=0, revocations=0)
        assert r1.keys() == r2.keys()

    def test_keys_used_in_dict_comprehension(self):
        r = _make_merge_result(added=5, conflicts=2, revocations=1)
        d = {k: getattr(r, k) for k in r.keys()}
        assert d == {"added_count": 5, "conflict_count": 2, "revocations_copied": 1}

    def test_keys_consistent_with_iter(self):
        r = _make_merge_result(added=3, conflicts=1, revocations=0)
        iter_keys = [k for k, _v in r]
        assert r.keys() == iter_keys

    def test_keys_independent_of_values(self):
        for added in (0, 10, 100):
            r = _make_merge_result(added=added)
            assert r.keys() == ["added_count", "conflict_count", "revocations_copied"]

    def test_keys_can_be_iterated(self):
        r = _make_merge_result()
        count = sum(1 for _ in r.keys())
        assert count == 3

    def test_first_key(self):
        r = _make_merge_result()
        assert r.keys()[0] == "added_count"

    def test_last_key(self):
        r = _make_merge_result()
        assert r.keys()[-1] == "revocations_copied"


# ---------------------------------------------------------------------------
# 2. IPFSReloadResult.iter_succeeded()
# ---------------------------------------------------------------------------

class TestIPFSReloadResultIterSucceeded:
    def test_all_succeed_yields_all(self):
        r = _make_reload_result(count=3, failed=0)
        pairs = list(r.iter_succeeded())
        assert len(pairs) == 3

    def test_all_fail_yields_none(self):
        r = _make_reload_result(count=3, failed=3)
        assert list(r.iter_succeeded()) == []

    def test_mixed_yields_only_succeeded(self):
        r = _make_reload_result(count=4, failed=1)
        pairs = list(r.iter_succeeded())
        assert len(pairs) == 3

    def test_yields_name_cid_tuples(self):
        r = _make_reload_result(count=2, failed=0)
        for name, cid in r.iter_succeeded():
            assert isinstance(name, str)
            assert isinstance(cid, str)

    def test_cids_are_non_none(self):
        r = _make_reload_result(count=4, failed=2)
        for _name, cid in r.iter_succeeded():
            assert cid is not None

    def test_count_matches_total_minus_failed(self):
        r = _make_reload_result(count=6, failed=2)
        assert len(list(r.iter_succeeded())) == r.count - r.total_failed

    def test_iter_succeeded_and_iter_failed_partition(self):
        r = _make_reload_result(count=5, failed=2)
        succeeded_names = {n for n, _ in r.iter_succeeded()}
        failed_names = {n for n, _ in r.iter_failed()}
        all_names = set(r.pin_results.keys())
        assert succeeded_names | failed_names == all_names
        assert succeeded_names & failed_names == set()

    def test_empty_result_yields_none(self):
        r = _make_reload_result(count=0, failed=0)
        assert list(r.iter_succeeded()) == []

    def test_single_success(self):
        r = _make_reload_result(count=1, failed=0)
        pairs = list(r.iter_succeeded())
        assert len(pairs) == 1
        _name, cid = pairs[0]
        assert cid is not None

    def test_iter_succeeded_is_generator(self):
        import types
        r = _make_reload_result(count=2, failed=0)
        assert isinstance(r.iter_succeeded(), types.GeneratorType)


# ---------------------------------------------------------------------------
# 3. PubSubBus.topic_sid_map()
# ---------------------------------------------------------------------------

class TestPubSubBusTopicSidMap:
    def test_empty_bus_returns_empty_dict(self):
        bus = _make_bus()
        assert bus.topic_sid_map() == {}

    def test_single_subscription_in_map(self):
        bus = _make_bus()
        sid = bus.subscribe("receipts", lambda t, p: None)
        m = bus.topic_sid_map()
        assert "receipts" in m
        assert m["receipts"] == [sid]

    def test_sids_are_sorted(self):
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        sid1 = bus.subscribe("topic", h1)
        sid2 = bus.subscribe("topic", h2)
        m = bus.topic_sid_map()
        assert m["topic"] == sorted([sid1, sid2])

    def test_multiple_topics(self):
        bus = _make_bus()
        bus.subscribe("a", lambda t, p: None)
        bus.subscribe("b", lambda t, p: None)
        m = bus.topic_sid_map()
        assert set(m.keys()) == {"a", "b"}

    def test_consistent_with_subscriber_ids(self):
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        bus.subscribe("receipts", h1)
        bus.subscribe("receipts", h2)
        bus.subscribe("audit", h1)
        m = bus.topic_sid_map()
        assert m["receipts"] == bus.subscriber_ids("receipts")
        assert m["audit"] == bus.subscriber_ids("audit")

    def test_empty_after_clear_all(self):
        bus = _make_bus()
        bus.subscribe("x", lambda t, p: None)
        bus.clear_all()
        assert bus.topic_sid_map() == {}

    def test_removed_topic_not_in_map(self):
        bus = _make_bus()
        sid = bus.subscribe("z", lambda t, p: None)
        bus.unsubscribe_by_id(sid)
        assert "z" not in bus.topic_sid_map()

    def test_returns_dict_type(self):
        bus = _make_bus()
        assert isinstance(bus.topic_sid_map(), dict)

    def test_values_are_lists(self):
        bus = _make_bus()
        bus.subscribe("q", lambda t, p: None)
        for v in bus.topic_sid_map().values():
            assert isinstance(v, list)

    def test_does_not_mutate_internal_state(self):
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        bus.subscribe("receipts", h)
        m = bus.topic_sid_map()
        m["receipts"].clear()  # mutate the copy
        # Original still has the subscription
        assert bus.subscription_count("receipts") == 1


# ---------------------------------------------------------------------------
# 4. ComplianceChecker.backup_names()
# ---------------------------------------------------------------------------

class TestComplianceCheckerBackupNames:
    def test_no_backups_returns_empty_list(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        try:
            assert ComplianceChecker.backup_names(path) == []
        finally:
            os.unlink(path)

    def test_one_backup_returns_one_name(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            names = ComplianceChecker.backup_names(path)
            assert len(names) == 1
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_names_are_basenames_only(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            names = ComplianceChecker.backup_names(path)
            for name in names:
                assert os.sep not in name
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_names_end_with_bak(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            names = ComplianceChecker.backup_names(path)
            for name in names:
                assert ".bak" in name
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_two_backups_returns_two_names(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        bak1 = path + ".bak.1"
        try:
            with open(bak, "w") as bf:
                bf.write("new")
            with open(bak1, "w") as bf:
                bf.write("old")
            names = ComplianceChecker.backup_names(path)
            assert len(names) == 2
        finally:
            os.unlink(path)
            for p in (bak, bak1):
                if os.path.exists(p):
                    os.unlink(p)

    def test_count_matches_backup_count(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            assert len(ComplianceChecker.backup_names(path)) == \
                ComplianceChecker.backup_count(path)
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_no_directory_separators_in_names(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            for name in ComplianceChecker.backup_names(path):
                assert "/" not in name and "\\" not in name
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_returns_list_type(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        try:
            result = ComplianceChecker.backup_names(path)
            assert isinstance(result, list)
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 5. E2E: Session 82 combined flows
# ---------------------------------------------------------------------------

class TestE2ESession82:
    def test_keys_round_trip_via_dict_comprehension(self):
        """keys() enables safe attribute access without knowing field names."""
        r = _make_merge_result(added=7, conflicts=3, revocations=2)
        d = {k: getattr(r, k) for k in r.keys()}
        assert d["added_count"] == 7
        assert d["conflict_count"] == 3
        assert d["revocations_copied"] == 2

    def test_iter_succeeded_filtering_for_cid_map(self):
        """iter_succeeded() lets callers build a name→CID mapping."""
        r = _make_reload_result(count=5, failed=2)
        cid_map = dict(r.iter_succeeded())
        assert len(cid_map) == 3
        for cid in cid_map.values():
            assert cid is not None

    def test_topic_sid_map_consistent_after_unsubscribe(self):
        """topic_sid_map stays accurate after unsubscribe_by_id."""
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        sid1 = bus.subscribe("receipts", h1)
        _sid2 = bus.subscribe("receipts", h2)
        bus.unsubscribe_by_id(sid1)
        m = bus.topic_sid_map()
        assert sid1 not in m.get("receipts", [])

    def test_backup_names_after_purge(self):
        """backup_names returns empty list after purge_bak_files."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.enc")
            bak = path + ".bak"
            with open(path, "w") as f:
                f.write("v1")
            with open(bak, "w") as f:
                f.write("bak")
            assert len(ComplianceChecker.backup_names(path)) >= 1
            ComplianceChecker.purge_bak_files(path)
            assert ComplianceChecker.backup_names(path) == []
