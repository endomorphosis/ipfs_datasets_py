"""Session 83 — MCP++ v38 Next Steps.

Implements tests for:
  1. MergeResult.values()                          (list of field values)
  2. IPFSReloadResult.iter_all()                   (generator of (name, cid_or_none))
  3. PubSubBus.total_subscriptions()               (len(_sid_map))
  4. ComplianceChecker.newest_backup_name(path)    (basename of newest .bak)
  5. E2E: values() consistency, iter_all coverage,
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

    def test_values_zero_result(self):
        r = _make_merge_result()
        assert r.values() == [0, 0, 0]

    def test_values_consistent_with_keys(self):
        r = _make_merge_result(added=7, conflicts=3, revocations=2)
        d_from_keys = {k: getattr(r, k) for k in r.keys()}
        d_from_values = dict(zip(r.keys(), r.values()))
        assert d_from_keys == d_from_values

    def test_values_consistent_with_iter(self):
        r = _make_merge_result(added=4, conflicts=1, revocations=0)
        iter_values = [v for _k, v in r]
        assert r.values() == iter_values

    def test_values_order_matches_keys(self):
        r = _make_merge_result(added=3, conflicts=2, revocations=1)
        for key, val in zip(r.keys(), r.values()):
            assert getattr(r, key) == val

    def test_values_independent_of_other_results(self):
        r1 = _make_merge_result(added=10, conflicts=0, revocations=0)
        r2 = _make_merge_result(added=0, conflicts=10, revocations=5)
        assert r1.values() != r2.values()

    def test_values_can_be_summed(self):
        r = _make_merge_result(added=3, conflicts=2, revocations=1)
        assert sum(r.values()) == 6

    def test_values_first_element_is_added_count(self):
        r = _make_merge_result(added=99)
        assert r.values()[0] == 99


# ---------------------------------------------------------------------------
# 2. IPFSReloadResult.iter_all()
# ---------------------------------------------------------------------------

class TestIPFSReloadResultIterAll:
    def test_iter_all_yields_all_entries(self):
        r = _make_reload_result(count=4, failed=1)
        pairs = list(r.iter_all())
        assert len(pairs) == 4

    def test_iter_all_empty_yields_nothing(self):
        r = _make_reload_result(count=0, failed=0)
        assert list(r.iter_all()) == []

    def test_iter_all_all_succeed(self):
        r = _make_reload_result(count=3, failed=0)
        pairs = list(r.iter_all())
        assert len(pairs) == 3
        for _name, cid in pairs:
            assert cid is not None

    def test_iter_all_all_fail(self):
        r = _make_reload_result(count=3, failed=3)
        pairs = list(r.iter_all())
        assert len(pairs) == 3
        for _name, cid in pairs:
            assert cid is None

    def test_iter_all_names_are_strings(self):
        r = _make_reload_result(count=3, failed=1)
        for name, _cid in r.iter_all():
            assert isinstance(name, str)

    def test_iter_all_matches_pin_results_keys(self):
        r = _make_reload_result(count=4, failed=2)
        all_names = {n for n, _ in r.iter_all()}
        assert all_names == set(r.pin_results.keys())

    def test_iter_all_partitions_with_iter_failed_and_iter_succeeded(self):
        r = _make_reload_result(count=5, failed=2)
        all_names = {n for n, _ in r.iter_all()}
        succeeded_names = {n for n, _ in r.iter_succeeded()}
        failed_names = {n for n, _ in r.iter_failed()}
        assert all_names == succeeded_names | failed_names

    def test_iter_all_count_matches_len(self):
        r = _make_reload_result(count=6, failed=3)
        assert sum(1 for _ in r.iter_all()) == len(r)

    def test_iter_all_is_generator(self):
        import types
        r = _make_reload_result(count=2)
        assert isinstance(r.iter_all(), types.GeneratorType)

    def test_iter_all_cid_none_for_failed(self):
        r = _make_reload_result(count=3, failed=1)
        failed_from_all = [(n, c) for n, c in r.iter_all() if c is None]
        assert len(failed_from_all) == 1


# ---------------------------------------------------------------------------
# 3. PubSubBus.total_subscriptions()
# ---------------------------------------------------------------------------

class TestPubSubBusTotalSubscriptions:
    def test_empty_bus_returns_zero(self):
        bus = _make_bus()
        assert bus.total_subscriptions() == 0

    def test_single_subscription_returns_one(self):
        bus = _make_bus()
        bus.subscribe("receipts", lambda t, p: None)
        assert bus.total_subscriptions() == 1

    def test_multiple_subscriptions_counted_individually(self):
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        bus.subscribe("a", h)
        bus.subscribe("b", h)
        assert bus.total_subscriptions() == 2

    def test_same_handler_multiple_topics_counted_each(self):
        bus = _make_bus()
        cb = lambda t, p: None  # noqa: E731
        bus.subscribe("x", cb)
        bus.subscribe("y", cb)
        bus.subscribe("z", cb)
        # 3 registrations even though handler_count == 1
        assert bus.total_subscriptions() == 3
        assert bus.handler_count() == 1

    def test_unsubscribe_reduces_count(self):
        bus = _make_bus()
        h = lambda t, p: None  # noqa: E731
        sid = bus.subscribe("topic", h)
        bus.unsubscribe_by_id(sid)
        assert bus.total_subscriptions() == 0

    def test_clear_all_resets_to_zero(self):
        bus = _make_bus()
        bus.subscribe("a", lambda t, p: None)
        bus.subscribe("b", lambda t, p: None)
        bus.clear_all()
        assert bus.total_subscriptions() == 0

    def test_consistent_with_sum_of_subscriber_counts(self):
        bus = _make_bus()
        h1 = lambda t, p: None  # noqa: E731
        h2 = lambda t, p: None  # noqa: E731
        bus.subscribe("receipts", h1)
        bus.subscribe("receipts", h2)
        bus.subscribe("audit", h1)
        topics = bus.topics()
        manual_sum = sum(bus.subscription_count(t) for t in topics)
        assert bus.total_subscriptions() == manual_sum

    def test_returns_int(self):
        bus = _make_bus()
        assert isinstance(bus.total_subscriptions(), int)

    def test_resubscribe_does_not_change_count(self):
        bus = _make_bus()
        h_old = lambda t, p: None  # noqa: E731
        h_new = lambda t, p: None  # noqa: E731
        bus.subscribe("topic", h_old)
        before = bus.total_subscriptions()
        bus.resubscribe(h_old, h_new)
        assert bus.total_subscriptions() == before

    def test_clear_topic_reduces_count(self):
        bus = _make_bus()
        bus.subscribe("a", lambda t, p: None)
        bus.subscribe("a", lambda t, p: None)
        bus.subscribe("b", lambda t, p: None)
        bus.clear_topic("a")
        assert bus.total_subscriptions() == 1


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

    def test_one_backup_returns_name(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            name = ComplianceChecker.newest_backup_name(path)
            assert name is not None
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_returns_basename_not_full_path(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            name = ComplianceChecker.newest_backup_name(path)
            assert os.sep not in name
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_returns_string_or_none(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        try:
            result = ComplianceChecker.newest_backup_name(path)
            assert result is None or isinstance(result, str)
        finally:
            os.unlink(path)

    def test_consistent_with_backup_names_first(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            names = ComplianceChecker.backup_names(path)
            newest = ComplianceChecker.newest_backup_name(path)
            if names:
                assert newest == names[0]
            else:
                assert newest is None
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_ends_with_dot_bak(self):
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

    def test_consistent_with_newest_backup_path(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.NamedTemporaryFile(delete=False, suffix=".enc") as f:
            path = f.name
        bak = path + ".bak"
        try:
            with open(bak, "w") as bf:
                bf.write("x")
            full_path = ComplianceChecker.newest_backup_path(path)
            name = ComplianceChecker.newest_backup_name(path)
            if full_path is not None:
                assert name == os.path.basename(full_path)
            else:
                assert name is None
        finally:
            os.unlink(path)
            if os.path.exists(bak):
                os.unlink(bak)

    def test_after_purge_returns_none(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "policy.enc")
            bak = path + ".bak"
            with open(path, "w") as f:
                f.write("v1")
            with open(bak, "w") as f:
                f.write("bak")
            assert ComplianceChecker.newest_backup_name(path) is not None
            ComplianceChecker.purge_bak_files(path)
            assert ComplianceChecker.newest_backup_name(path) is None


# ---------------------------------------------------------------------------
# 5. E2E: Session 83 combined flows
# ---------------------------------------------------------------------------

class TestE2ESession83:
    def test_values_zip_keys_round_trip(self):
        """values() zipped with keys() gives the same dict as dict(r)."""
        r = _make_merge_result(added=6, conflicts=2, revocations=1)
        d_zip = dict(zip(r.keys(), r.values()))
        d_iter = dict(r)
        assert d_zip == d_iter

    def test_iter_all_for_unified_audit_log(self):
        """iter_all() covers both succeeded and failed for an audit summary."""
        r = _make_reload_result(count=5, failed=2)
        succeeded = [(n, c) for n, c in r.iter_all() if c is not None]
        failed = [(n, c) for n, c in r.iter_all() if c is None]
        assert len(succeeded) + len(failed) == 5
        assert len(failed) == 2

    def test_total_subscriptions_vs_handler_count(self):
        """total_subscriptions counts registrations; handler_count deduplicates."""
        bus = _make_bus()
        shared = lambda t, p: None  # noqa: E731
        unique = lambda t, p: None  # noqa: E731
        bus.subscribe("a", shared)
        bus.subscribe("b", shared)
        bus.subscribe("a", unique)
        assert bus.total_subscriptions() == 3
        assert bus.handler_count() == 2  # shared + unique

    def test_newest_backup_name_rotate_cycle(self):
        """newest_backup_name tracks the primary .bak after rotation."""
        import shutil
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "rules.enc")
            with open(path, "w") as f:
                f.write("v1")
            bak = path + ".bak"
            shutil.copy2(path, bak)
            name_before = ComplianceChecker.newest_backup_name(path)
            assert name_before == os.path.basename(bak)
            # After rotate, .bak moves to .bak.1; .bak no longer exists
            ComplianceChecker.rotate_bak(path, max_keep=3)
            name_after = ComplianceChecker.newest_backup_name(path)
            # .bak is gone → newest is now .bak.1
            assert name_after == os.path.basename(path + ".bak.1")
