"""Session 84 — MCP++ v39 Next Steps.

Implements tests for:
  1. MergeResult.items()                          (list of (key, value) tuples)
  2. IPFSReloadResult.as_dict()                   ({name: cid_or_none} flat dict)
  3. PubSubBus.topics_with_count()                ([(topic, count)] sorted desc)
  4. ComplianceChecker.oldest_backup_name(path)   (basename of oldest .bak)
  5. E2E: items() triad, as_dict() round-trip,
          topics_with_count ordering, oldest+newest backup names together
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
# 1. MergeResult.items()
# ---------------------------------------------------------------------------

class TestMergeResultItems:
    def test_items_returns_list(self):
        r = _make_merge_result()
        assert isinstance(r.items(), list)

    def test_items_length_three(self):
        r = _make_merge_result()
        assert len(r.items()) == 3

    def test_items_are_tuples(self):
        r = _make_merge_result()
        for item in r.items():
            assert isinstance(item, tuple) and len(item) == 2

    def test_items_keys_match_keys_method(self):
        r = _make_merge_result(added=5, conflicts=2, revocations=1)
        assert [k for k, _v in r.items()] == r.keys()

    def test_items_values_match_values_method(self):
        r = _make_merge_result(added=5, conflicts=2, revocations=1)
        assert [v for _k, v in r.items()] == r.values()

    def test_items_consistent_with_iter(self):
        r = _make_merge_result(added=4, conflicts=3, revocations=2)
        assert r.items() == list(r)

    def test_items_construct_dict(self):
        r = _make_merge_result(added=7, conflicts=1, revocations=0)
        d = dict(r.items())
        assert d == {"added_count": 7, "conflict_count": 1, "revocations_copied": 0}

    def test_items_first_entry(self):
        r = _make_merge_result(added=9)
        assert r.items()[0] == ("added_count", 9)

    def test_items_last_entry(self):
        r = _make_merge_result(revocations=3)
        assert r.items()[-1] == ("revocations_copied", 3)

    def test_items_stable_across_calls(self):
        r = _make_merge_result(added=2, conflicts=5, revocations=1)
        assert r.items() == r.items()


# ---------------------------------------------------------------------------
# 2. IPFSReloadResult.as_dict()
# ---------------------------------------------------------------------------

class TestIPFSReloadResultAsDict:
    def test_as_dict_returns_dict(self):
        r = _make_reload_result(count=3)
        assert isinstance(r.as_dict(), dict)

    def test_as_dict_keys_are_policy_names(self):
        r = _make_reload_result(count=3, failed=1)
        assert set(r.as_dict().keys()) == set(r.pin_results.keys())

    def test_as_dict_values_match_pin_results(self):
        r = _make_reload_result(count=3, failed=1)
        for name, cid in r.as_dict().items():
            assert r.pin_results[name] == cid

    def test_as_dict_none_for_failed(self):
        r = _make_reload_result(count=3, failed=1)
        d = r.as_dict()
        none_count = sum(1 for v in d.values() if v is None)
        assert none_count == 1

    def test_as_dict_all_values_set_when_all_succeed(self):
        r = _make_reload_result(count=4, failed=0)
        d = r.as_dict()
        assert all(v is not None for v in d.values())

    def test_as_dict_empty_result(self):
        r = _make_reload_result(count=0, failed=0)
        assert r.as_dict() == {}

    def test_as_dict_matches_iter_all(self):
        r = _make_reload_result(count=5, failed=2)
        assert r.as_dict() == dict(r.iter_all())

    def test_as_dict_is_independent_copy(self):
        r = _make_reload_result(count=3, failed=0)
        d = r.as_dict()
        d.clear()  # mutating the copy should not affect pin_results
        assert len(r.pin_results) == 3

    def test_as_dict_length_equals_count(self):
        r = _make_reload_result(count=5, failed=2)
        assert len(r.as_dict()) == len(r.pin_results)

    def test_as_dict_serialisable_structure(self):
        import json
        r = _make_reload_result(count=3, failed=1)
        # values are str or None — JSON serialisable
        d = r.as_dict()
        for v in d.values():
            assert v is None or isinstance(v, str)


# ---------------------------------------------------------------------------
# 3. PubSubBus.topics_with_count()
# ---------------------------------------------------------------------------

class TestPubSubBusTopicsWithCount:
    def test_empty_bus_returns_empty_list(self):
        bus = _make_bus()
        assert bus.topics_with_count() == []

    def test_single_topic_single_handler(self):
        bus = _make_bus()
        bus.subscribe("receipts", lambda t, p: None)
        result = bus.topics_with_count()
        assert len(result) == 1
        topic, count = result[0]
        assert topic == "receipts"
        assert count == 1

    def test_sorted_descending_by_count(self):
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        h3 = lambda t, p: None  # noqa: E731
        bus.subscribe("low", h1)           # 1 subscriber
        bus.subscribe("high", h1)
        bus.subscribe("high", h2)
        bus.subscribe("high", h3)          # 3 subscribers
        bus.subscribe("mid", h1)
        bus.subscribe("mid", h2)           # 2 subscribers
        counts = [c for _t, c in bus.topics_with_count()]
        assert counts == sorted(counts, reverse=True)

    def test_all_topics_present(self):
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        bus.subscribe("a", h)
        bus.subscribe("b", h)
        topics = {t for t, _c in bus.topics_with_count()}
        assert topics == {"a", "b"}

    def test_returns_list_of_tuples(self):
        bus = _make_bus()
        bus.subscribe("x", lambda t, p: None)
        result = bus.topics_with_count()
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, tuple) and len(item) == 2

    def test_counts_are_positive_integers(self):
        bus = _make_bus()
        bus.subscribe("x", lambda t, p: None)
        for _t, count in bus.topics_with_count():
            assert isinstance(count, int) and count > 0

    def test_consistent_with_subscription_count(self):
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        bus.subscribe("receipts", h1)
        bus.subscribe("receipts", h2)
        bus.subscribe("audit", h1)
        for topic, count in bus.topics_with_count():
            assert count == bus.subscription_count(topic)

    def test_empty_after_clear_all(self):
        bus = _make_bus()
        bus.subscribe("x", lambda t, p: None)
        bus.clear_all()
        assert bus.topics_with_count() == []

    def test_highest_count_first(self):
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        h3 = lambda t, p: None  # noqa: E731
        bus.subscribe("popular", h1)
        bus.subscribe("popular", h2)
        bus.subscribe("popular", h3)
        bus.subscribe("lonely", h1)
        first_topic, first_count = bus.topics_with_count()[0]
        assert first_topic == "popular"
        assert first_count == 3

    def test_single_topic_after_unsubscribe(self):
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        sid = bus.subscribe("x", h)
        bus.unsubscribe_by_id(sid)
        assert bus.topics_with_count() == []


# ---------------------------------------------------------------------------
# 4. ComplianceChecker.oldest_backup_name()
# ---------------------------------------------------------------------------

class TestComplianceCheckerOldestBackupName:
    def test_no_backup_returns_none(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        try:
            assert ComplianceChecker.oldest_backup_name(path) is None
        finally:
            os.unlink(path)

    def test_one_backup_returns_basename(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            name = ComplianceChecker.oldest_backup_name(path)
            assert name is not None and os.sep not in name
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_returns_last_basename_in_list(self):
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
            name = ComplianceChecker.oldest_backup_name(path)
            assert name == os.path.basename(bak1)
        finally:
            os.unlink(path)
            for p in (bak, bak1):
                if os.path.exists(p):
                    os.unlink(p)

    def test_consistent_with_oldest_backup_path(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            full = ComplianceChecker.oldest_backup_path(path)
            name = ComplianceChecker.oldest_backup_name(path)
            if full is not None:
                assert name == os.path.basename(full)
            else:
                assert name is None
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_consistent_with_backup_names_last(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            names = ComplianceChecker.backup_names(path)
            oldest = ComplianceChecker.oldest_backup_name(path)
            if names:
                assert oldest == names[-1]
            else:
                assert oldest is None
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_no_dir_separator_in_name(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            name = ComplianceChecker.oldest_backup_name(path)
            assert name is not None
            assert "/" not in name and "\\" not in name
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_returns_none_after_purge(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.enc")
            with open(path, "w") as f:
                f.write("v1")
            with open(path + ".bak", "w") as f:
                f.write("bak")
            ComplianceChecker.purge_bak_files(path)
            assert ComplianceChecker.oldest_backup_name(path) is None

    def test_one_backup_newest_and_oldest_same(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            assert ComplianceChecker.newest_backup_name(path) == \
                ComplianceChecker.oldest_backup_name(path)
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)


# ---------------------------------------------------------------------------
# 5. E2E: Session 84 combined flows
# ---------------------------------------------------------------------------

class TestE2ESession84:
    def test_items_keys_values_triad(self):
        """items(), keys(), values() all describe the same data."""
        r = _make_merge_result(added=3, conflicts=1, revocations=2)
        assert dict(r.items()) == dict(zip(r.keys(), r.values()))
        assert [k for k, _v in r.items()] == r.keys()
        assert [v for _k, v in r.items()] == r.values()

    def test_as_dict_round_trip(self):
        """as_dict() produces the same mapping as dict(iter_all())."""
        r = _make_reload_result(count=6, failed=2)
        assert r.as_dict() == dict(r.iter_all())
        # all keys present
        assert set(r.as_dict().keys()) == set(r.pin_results.keys())

    def test_topics_with_count_ordering_and_consistency(self):
        """topics_with_count() is sorted desc and consistent with subscription_count."""
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        bus.subscribe("high", h1)
        bus.subscribe("high", h2)
        bus.subscribe("low", h1)
        twc = bus.topics_with_count()
        counts = [c for _t, c in twc]
        assert counts == sorted(counts, reverse=True)
        for topic, count in twc:
            assert bus.subscription_count(topic) == count

    def test_oldest_newest_backup_name_two_backups(self):
        """With two backups newest != oldest; each is a basename."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.enc")
            with open(path, "w") as f:
                f.write("v1")
            with open(path + ".bak", "w") as f:
                f.write("new")
            with open(path + ".bak.1", "w") as f:
                f.write("old")
            newest = ComplianceChecker.newest_backup_name(path)
            oldest = ComplianceChecker.oldest_backup_name(path)
            assert newest is not None and oldest is not None
            assert newest != oldest
            assert os.sep not in newest
            assert os.sep not in oldest
