"""Session 81 — MCP++ v36 Next Steps.

Implements tests for:
  1. MergeResult.__iter__              (yields (field, value) pairs)
  2. IPFSReloadResult.iter_failed()    (generator of (name, error) pairs)
  3. PubSubBus.subscriber_ids(topic)   (sorted SID list for a topic)
  4. ComplianceChecker.backup_summary(path)
  5. E2E: dict(result), iter_failed filtering, targeted unsubscribe, full purge flow
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
# 1. MergeResult.__iter__
# ---------------------------------------------------------------------------

class TestMergeResultIter:
    def test_iter_yields_three_pairs(self):
        r = _make_merge_result(added=3, conflicts=1, revocations=2)
        pairs = list(r)
        assert len(pairs) == 3

    def test_iter_keys(self):
        r = _make_merge_result(added=5, conflicts=0, revocations=1)
        keys = [k for k, _v in r]
        assert keys == ["added_count", "conflict_count", "revocations_copied"]

    def test_iter_values_match_attrs(self):
        r = _make_merge_result(added=7, conflicts=2, revocations=3)
        pairs = list(r)
        assert pairs[0] == ("added_count", 7)
        assert pairs[1] == ("conflict_count", 2)
        assert pairs[2] == ("revocations_copied", 3)

    def test_dict_conversion(self):
        r = _make_merge_result(added=4, conflicts=1, revocations=0)
        d = dict(r)
        assert d == {"added_count": 4, "conflict_count": 1, "revocations_copied": 0}

    def test_dict_zero_values(self):
        r = _make_merge_result()
        d = dict(r)
        assert d == {"added_count": 0, "conflict_count": 0, "revocations_copied": 0}

    def test_iter_multiple_times(self):
        r = _make_merge_result(added=2, conflicts=3, revocations=1)
        assert list(r) == list(r)

    def test_iter_unpacking(self):
        r = _make_merge_result(added=10, conflicts=5, revocations=2)
        (k1, v1), (k2, v2), (k3, v3) = r
        assert k1 == "added_count" and v1 == 10
        assert k2 == "conflict_count" and v2 == 5
        assert k3 == "revocations_copied" and v3 == 2

    def test_dict_added_count_matches_int(self):
        r = _make_merge_result(added=6)
        d = dict(r)
        assert d["added_count"] == int(r)

    def test_dict_roundtrip_via_iter(self):
        r = _make_merge_result(added=3, conflicts=2, revocations=1)
        d = dict(r)
        assert d["added_count"] == r.added_count
        assert d["conflict_count"] == r.conflict_count
        assert d["revocations_copied"] == r.revocations_copied

    def test_sum_via_iter(self):
        results = [_make_merge_result(added=i) for i in range(5)]
        # Sum added_count across list using dict(r)["added_count"]
        total = sum(dict(r)["added_count"] for r in results)
        assert total == 0 + 1 + 2 + 3 + 4


# ---------------------------------------------------------------------------
# 2. IPFSReloadResult.iter_failed
# ---------------------------------------------------------------------------

class TestIPFSReloadResultIterFailed:
    def test_iter_failed_none_when_all_succeed(self):
        r = _make_reload_result(count=3, failed=0)
        assert list(r.iter_failed()) == []

    def test_iter_failed_yields_one_pair(self):
        r = _make_reload_result(count=3, failed=1)
        pairs = list(r.iter_failed())
        assert len(pairs) == 1

    def test_iter_failed_name_is_string(self):
        r = _make_reload_result(count=2, failed=1)
        for name, _err in r.iter_failed():
            assert isinstance(name, str)

    def test_iter_failed_error_is_string(self):
        r = _make_reload_result(count=2, failed=1)
        for _name, err in r.iter_failed():
            assert isinstance(err, str)

    def test_iter_failed_default_error_text(self):
        r = _make_reload_result(count=2, failed=1)
        for _name, err in r.iter_failed():
            assert err == "unknown error"

    def test_iter_failed_uses_pin_errors_when_present(self):
        errors = {"f0": "connection timeout"}
        r = _make_reload_result(count=3, failed=1, pin_errors=errors)
        pairs = list(r.iter_failed())
        assert len(pairs) == 1
        name, err = pairs[0]
        assert name == "f0"
        assert err == "connection timeout"

    def test_iter_failed_multiple_failures(self):
        r = _make_reload_result(count=5, failed=3)
        pairs = list(r.iter_failed())
        assert len(pairs) == 3

    def test_iter_failed_count_matches_total_failed(self):
        r = _make_reload_result(count=6, failed=4)
        assert len(list(r.iter_failed())) == r.total_failed

    def test_iter_failed_no_duplicates(self):
        r = _make_reload_result(count=4, failed=2)
        names = [n for n, _ in r.iter_failed()]
        assert len(names) == len(set(names))

    def test_iter_failed_mixed_errors(self):
        errors = {"f0": "timeout", "f1": "quota exceeded"}
        r = _make_reload_result(count=4, failed=2, pin_errors=errors)
        result_map = dict(r.iter_failed())
        assert result_map.get("f0") == "timeout"
        assert result_map.get("f1") == "quota exceeded"


# ---------------------------------------------------------------------------
# 3. PubSubBus.subscriber_ids
# ---------------------------------------------------------------------------

class TestPubSubBusSubscriberIds:
    def test_empty_topic_returns_empty_list(self):
        bus = _make_bus()
        assert bus.subscriber_ids("no_such_topic") == []

    def test_single_subscription_returns_one_sid(self):
        bus = _make_bus()
        sid = bus.subscribe("receipts", lambda t, p: None)
        ids = bus.subscriber_ids("receipts")
        assert ids == [sid]

    def test_multiple_subscriptions_same_topic(self):
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        sid1 = bus.subscribe("receipts", h1)
        sid2 = bus.subscribe("receipts", h2)
        ids = bus.subscriber_ids("receipts")
        assert sorted(ids) == sorted([sid1, sid2])

    def test_returns_sorted_list(self):
        bus = _make_bus()
        sids = []
        for _ in range(5):
            sids.append(bus.subscribe("audit", lambda t, p: None))
        ids = bus.subscriber_ids("audit")
        assert ids == sorted(ids)

    def test_unsubscribed_sid_not_returned(self):
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        sid = bus.subscribe("receipts", h)
        bus.unsubscribe_by_id(sid)
        assert bus.subscriber_ids("receipts") == []

    def test_does_not_return_sids_for_other_topics(self):
        bus = _make_bus()
        bus.subscribe("topic_a", lambda t, p: None)
        sid_b = bus.subscribe("topic_b", lambda t, p: None)
        ids_b = bus.subscriber_ids("topic_b")
        assert ids_b == [sid_b]

    def test_returns_list_type(self):
        bus = _make_bus()
        bus.subscribe("x", lambda t, p: None)
        assert isinstance(bus.subscriber_ids("x"), list)

    def test_each_sid_is_int(self):
        bus = _make_bus()
        bus.subscribe("y", lambda t, p: None)
        for sid in bus.subscriber_ids("y"):
            assert isinstance(sid, int)

    def test_returns_empty_after_clear_topic(self):
        bus = _make_bus()
        bus.subscribe("z", lambda t, p: None)
        bus.clear_topic("z")
        assert bus.subscriber_ids("z") == []

    def test_returns_empty_after_clear_all(self):
        bus = _make_bus()
        bus.subscribe("a", lambda t, p: None)
        bus.subscribe("b", lambda t, p: None)
        bus.clear_all()
        assert bus.subscriber_ids("a") == []
        assert bus.subscriber_ids("b") == []


# ---------------------------------------------------------------------------
# 4. ComplianceChecker.backup_summary
# ---------------------------------------------------------------------------

class TestComplianceCheckerBackupSummary:
    def test_no_backups_returns_zero_count(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        try:
            summary = ComplianceChecker.backup_summary(path)
            assert summary["count"] == 0
        finally:
            os.unlink(path)

    def test_no_backups_all_none(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        try:
            summary = ComplianceChecker.backup_summary(path)
            assert summary["newest"] is None
            assert summary["oldest"] is None
            assert summary["newest_age"] is None
            assert summary["oldest_age"] is None
        finally:
            os.unlink(path)

    def test_one_backup_count_one(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("backup")
            summary = ComplianceChecker.backup_summary(path)
            assert summary["count"] == 1
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_one_backup_newest_oldest_same(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("backup")
            summary = ComplianceChecker.backup_summary(path)
            assert summary["newest"] == bak
            assert summary["oldest"] == bak
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_two_backups_count_two(self):
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
            summary = ComplianceChecker.backup_summary(path)
            assert summary["count"] == 2
        finally:
            os.unlink(path)
            for p in (bak, bak1):
                if os.path.exists(p):
                    os.unlink(p)

    def test_two_backups_newest_and_oldest_differ(self):
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
            summary = ComplianceChecker.backup_summary(path)
            assert summary["newest"] == bak
            assert summary["oldest"] == bak1
        finally:
            os.unlink(path)
            for p in (bak, bak1):
                if os.path.exists(p):
                    os.unlink(p)

    def test_ages_are_floats_when_backup_exists(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            summary = ComplianceChecker.backup_summary(path)
            assert isinstance(summary["newest_age"], float)
            assert isinstance(summary["oldest_age"], float)
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_summary_keys(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        try:
            summary = ComplianceChecker.backup_summary(path)
            assert set(summary.keys()) == {"count", "newest", "oldest",
                                           "newest_age", "oldest_age"}
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 5. E2E: combined session 81 flows
# ---------------------------------------------------------------------------

class TestE2ESession81:
    def test_merge_result_dict_packing(self):
        """dict(result) produces correct field map."""
        r = _make_merge_result(added=5, conflicts=2, revocations=1)
        d = dict(r)
        assert d["added_count"] == 5
        assert d["conflict_count"] == 2
        assert d["revocations_copied"] == 1

    def test_iter_failed_targeted_retry(self):
        """iter_failed() allows building a retry list."""
        errors = {"f0": "network error", "f1": "quota"}
        r = _make_reload_result(count=5, failed=2, pin_errors=errors)
        retry_names = [n for n, _e in r.iter_failed()]
        assert "f0" in retry_names
        assert "f1" in retry_names
        assert len(retry_names) == 2

    def test_subscriber_ids_targeted_unsubscribe(self):
        """subscriber_ids enables targeted bulk-unsubscribe."""
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        bus.subscribe("receipts", h1)
        bus.subscribe("receipts", h2)
        assert bus.subscription_count("receipts") == 2
        for sid in list(bus.subscriber_ids("receipts")):
            bus.unsubscribe_by_id(sid)
        assert bus.subscription_count("receipts") == 0

    def test_backup_summary_after_rotate(self):
        """backup_summary reflects state after manually creating backup files."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        import shutil
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.enc")
            with open(path, "w") as f:
                f.write("v1")
            # Create a .bak file manually, then rotate to .bak.1
            bak = path + ".bak"
            shutil.copy2(path, bak)
            ComplianceChecker.rotate_bak(path, max_keep=3)
            # Now create a second .bak
            shutil.copy2(path, bak)
            summary = ComplianceChecker.backup_summary(path)
            assert summary["count"] >= 1
            assert summary["newest"] is not None
            assert summary["oldest"] is not None
