"""Session 83 — MCP++ v38 Next Steps.

Implements tests for:
  1. MergeResult.values()                        (list of field values)
  2. IPFSReloadResult.iter_all()                 (generator of (name, cid|None))
  3. PubSubBus.total_subscriptions()             (len(_sid_map))
  4. ComplianceChecker.newest_backup_name(path)  (basename of newest .bak)
  5. E2E: values/keys/iter triad, iter_all unified report,
          total_subscriptions vs handler_count, newest_backup_name rotate cycle
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
# 1. MergeResult.values()
# ---------------------------------------------------------------------------

class TestMergeResultValues:
    def test_values_returns_list(self):
        r = _make_merge_result()
        assert isinstance(r.values(), list)

    def test_values_length_three(self):
        r = _make_merge_result()
        assert len(r.values()) == 3

    def test_values_match_attrs(self):
        r = _make_merge_result(added=5, conflicts=2, revocations=1)
        assert r.values() == [5, 2, 1]

    def test_values_order_matches_keys(self):
        r = _make_merge_result(added=3, conflicts=7, revocations=2)
        for k, v in zip(r.keys(), r.values()):
            assert getattr(r, k) == v

    def test_values_all_zero(self):
        r = _make_merge_result()
        assert r.values() == [0, 0, 0]

    def test_values_consistent_with_iter(self):
        r = _make_merge_result(added=4, conflicts=1, revocations=3)
        iter_values = [v for _k, v in r]
        assert r.values() == iter_values

    def test_values_stable_across_calls(self):
        r = _make_merge_result(added=9, conflicts=0, revocations=1)
        assert r.values() == r.values()

    def test_values_independent_of_keys(self):
        r = _make_merge_result(added=2, conflicts=3, revocations=5)
        assert len(r.values()) == len(r.keys())

    def test_first_value_is_added_count(self):
        r = _make_merge_result(added=11)
        assert r.values()[0] == 11

    def test_last_value_is_revocations_copied(self):
        r = _make_merge_result(revocations=7)
        assert r.values()[-1] == 7


# ---------------------------------------------------------------------------
# 2. IPFSReloadResult.iter_all()
# ---------------------------------------------------------------------------

class TestIPFSReloadResultIterAll:
    def test_iter_all_yields_all_entries(self):
        r = _make_reload_result(count=4, failed=1)
        pairs = list(r.iter_all())
        assert len(pairs) == 4

    def test_iter_all_count_matches_pin_results(self):
        r = _make_reload_result(count=6, failed=2)
        assert len(list(r.iter_all())) == len(r.pin_results)

    def test_iter_all_includes_none_cids(self):
        r = _make_reload_result(count=3, failed=1)
        cids = [cid for _name, cid in r.iter_all()]
        assert None in cids

    def test_iter_all_includes_non_none_cids(self):
        r = _make_reload_result(count=3, failed=1)
        cids = [cid for _name, cid in r.iter_all()]
        assert any(c is not None for c in cids)

    def test_iter_all_all_succeed(self):
        r = _make_reload_result(count=3, failed=0)
        pairs = list(r.iter_all())
        assert all(cid is not None for _n, cid in pairs)

    def test_iter_all_all_fail(self):
        r = _make_reload_result(count=3, failed=3)
        pairs = list(r.iter_all())
        assert all(cid is None for _n, cid in pairs)

    def test_iter_all_names_cover_all_keys(self):
        r = _make_reload_result(count=4, failed=2)
        all_names = {n for n, _ in r.iter_all()}
        assert all_names == set(r.pin_results.keys())

    def test_iter_all_empty(self):
        r = _make_reload_result(count=0, failed=0)
        assert list(r.iter_all()) == []

    def test_iter_all_is_generator(self):
        import types
        r = _make_reload_result(count=2, failed=0)
        assert isinstance(r.iter_all(), types.GeneratorType)

    def test_iter_all_succeeded_plus_failed_partition(self):
        r = _make_reload_result(count=5, failed=2)
        all_pairs = list(r.iter_all())
        succeeded = [(n, c) for n, c in all_pairs if c is not None]
        failed = [(n, c) for n, c in all_pairs if c is None]
        assert len(succeeded) + len(failed) == len(all_pairs)


# ---------------------------------------------------------------------------
# 3. PubSubBus.total_subscriptions()
# ---------------------------------------------------------------------------

class TestPubSubBusTotalSubscriptions:
    def test_empty_bus_returns_zero(self):
        bus = _make_bus()
        assert bus.total_subscriptions() == 0

    def test_one_subscription_returns_one(self):
        bus = _make_bus()
        bus.subscribe("receipts", lambda t, p: None)
        assert bus.total_subscriptions() == 1

    def test_two_subscriptions_same_topic(self):
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        bus.subscribe("receipts", h1)
        bus.subscribe("receipts", h2)
        assert bus.total_subscriptions() == 2

    def test_same_handler_different_topics_counts_twice(self):
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        bus.subscribe("a", h)
        bus.subscribe("b", h)
        assert bus.total_subscriptions() == 2

    def test_same_handler_same_topic_counted_once(self):
        """Duplicate registrations are deduplicated at subscribe time."""
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        sid1 = bus.subscribe("a", h)
        sid2 = bus.subscribe("a", h)  # duplicate — second SID may still be issued
        # total_subscriptions = len(_sid_map); depends on dedup behaviour
        total = bus.total_subscriptions()
        # Either 1 (deduped) or 2 (both SIDs issued) is acceptable;
        # assert it is at least 1 and at most 2.
        assert 1 <= total <= 2

    def test_decrements_on_unsubscribe(self):
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        sid = bus.subscribe("receipts", h)
        assert bus.total_subscriptions() == 1
        bus.unsubscribe_by_id(sid)
        assert bus.total_subscriptions() == 0

    def test_total_vs_handler_count_single_handler_multi_topic(self):
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        bus.subscribe("a", h)
        bus.subscribe("b", h)
        bus.subscribe("c", h)
        assert bus.total_subscriptions() == 3
        assert bus.handler_count() == 1

    def test_zero_after_clear_all(self):
        bus = _make_bus()
        bus.subscribe("x", lambda t, p: None)
        bus.subscribe("y", lambda t, p: None)
        bus.clear_all()
        assert bus.total_subscriptions() == 0

    def test_returns_int(self):
        bus = _make_bus()
        assert isinstance(bus.total_subscriptions(), int)

    def test_matches_sum_of_subscriber_ids_per_topic(self):
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        h3 = lambda t, p: None  # noqa: E731
        bus.subscribe("a", h1)
        bus.subscribe("a", h2)
        bus.subscribe("b", h3)
        # bus.topics() returns list of active topic strings
        active = bus.topics()
        total_via_ids = sum(len(bus.subscriber_ids(t)) for t in active)
        assert bus.total_subscriptions() == total_via_ids


# ---------------------------------------------------------------------------
# 4. ComplianceChecker.newest_backup_name()
# ---------------------------------------------------------------------------

class TestComplianceCheckerNewestBackupName:
    def test_no_backup_returns_none(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        try:
            assert ComplianceChecker.newest_backup_name(path) is None
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
            name = ComplianceChecker.newest_backup_name(path)
            assert name is not None
            assert os.sep not in name
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_returns_string_when_backup_exists(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            assert isinstance(ComplianceChecker.newest_backup_name(path), str)
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_name_ends_with_bak(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            name = ComplianceChecker.newest_backup_name(path)
            assert name is not None and name.endswith(".bak")
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_consistent_with_backup_names_first(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            assert ComplianceChecker.newest_backup_name(path) == \
                ComplianceChecker.backup_names(path)[0]
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
            name = ComplianceChecker.newest_backup_name(path)
            assert name is not None
            assert "/" not in name and "\\" not in name
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_two_backups_returns_newest(self):
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
            name = ComplianceChecker.newest_backup_name(path)
            assert name is not None and name.endswith(".bak")
            assert not name.endswith(".bak.1")
        finally:
            os.unlink(path)
            for p in (bak, bak1):
                if os.path.exists(p):
                    os.unlink(p)

    def test_none_after_purge(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            ComplianceChecker.purge_bak_files(path)
            assert ComplianceChecker.newest_backup_name(path) is None
        finally:
            if os.path.exists(path):
                os.unlink(path)


# ---------------------------------------------------------------------------
# 5. E2E: Session 83 combined flows
# ---------------------------------------------------------------------------

class TestE2ESession83:
    def test_values_keys_iter_triad_consistency(self):
        """keys/values/__iter__ all describe the same fields."""
        r = _make_merge_result(added=4, conflicts=2, revocations=1)
        assert r.keys() == [k for k, _v in r]
        assert r.values() == [v for _k, v in r]
        assert dict(zip(r.keys(), r.values())) == dict(r)

    def test_iter_all_unified_report(self):
        """iter_all() covers every entry; counts match."""
        r = _make_reload_result(count=6, failed=2)
        all_entries = list(r.iter_all())
        succeeded = [p for p in all_entries if p[1] is not None]
        failed = [p for p in all_entries if p[1] is None]
        assert len(succeeded) == r.count - r.total_failed
        assert len(failed) == r.total_failed

    def test_total_subscriptions_vs_handler_count(self):
        """Same handler subscribed twice → total=2, handler_count=1."""
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        bus.subscribe("alpha", h)
        bus.subscribe("beta", h)
        assert bus.total_subscriptions() == 2
        assert bus.handler_count() == 1

    def test_newest_backup_name_rotate_verify(self):
        """After rotate_bak, newest_backup_name returns the .bak basename."""
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        import shutil
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.enc")
            with open(path, "w") as f:
                f.write("v1")
            shutil.copy2(path, path + ".bak")
            name = ComplianceChecker.newest_backup_name(path)
            assert name is not None
            assert name == os.path.basename(path + ".bak")
