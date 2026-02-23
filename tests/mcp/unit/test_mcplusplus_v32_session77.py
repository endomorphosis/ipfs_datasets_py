"""Session 77 — v32 Next Steps

Tests for:
1. MergeResult.__repr__
2. IPFSReloadResult.__repr__
3. PubSubBus.handler_topics(handler)
4. ComplianceChecker.backup_age(path)
5. E2E diagnostics / health-check scenario
"""
import os
import tempfile
import time

import pytest

from ipfs_datasets_py.mcp_server.ucan_delegation import MergeResult
from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker


# ---------------------------------------------------------------------------
# 1. MergeResult.__repr__
# ---------------------------------------------------------------------------

class TestMergeResultRepr:
    def test_repr_basic(self):
        r = MergeResult(added_count=3, conflict_count=1, revocations_copied=0)
        s = repr(r)
        assert "MergeResult" in s
        assert "added=3" in s
        assert "conflicts=1" in s
        assert "rate=" in s

    def test_repr_rate_value(self):
        r = MergeResult(added_count=3, conflict_count=1, revocations_copied=0)
        # total=4, import_rate=0.75 → 75.0%
        assert "75.0%" in repr(r)

    def test_repr_all_added(self):
        r = MergeResult(added_count=5, conflict_count=0, revocations_copied=0)
        assert "rate=100.0%" in repr(r)

    def test_repr_zero_total(self):
        r = MergeResult(added_count=0, conflict_count=0, revocations_copied=0)
        # import_rate=0.0 when total==0
        assert "rate=0.0%" in repr(r)

    def test_repr_all_conflicts(self):
        r = MergeResult(added_count=0, conflict_count=4, revocations_copied=0)
        assert "added=0" in repr(r)
        assert "conflicts=4" in repr(r)
        assert "rate=0.0%" in repr(r)

    def test_repr_is_str(self):
        r = MergeResult(added_count=2, conflict_count=2, revocations_copied=1)
        assert isinstance(repr(r), str)

    def test_repr_with_revocations_copied(self):
        r = MergeResult(added_count=2, conflict_count=0, revocations_copied=3)
        s = repr(r)
        assert "added=2" in s
        assert "conflicts=0" in s

    def test_repr_decimal_rate(self):
        r = MergeResult(added_count=1, conflict_count=2, revocations_copied=0)
        # total=3, import_rate=1/3 ≈ 33.3%
        s = repr(r)
        assert "33.3%" in s


# ---------------------------------------------------------------------------
# 2. IPFSReloadResult.__repr__
# ---------------------------------------------------------------------------

class TestIPFSReloadResultRepr:
    def test_repr_basic(self):
        r = IPFSReloadResult(
            count=4,
            pin_results={"a": "Qm1", "b": "Qm2", "c": "Qm3", "d": None},
        )
        s = repr(r)
        assert "IPFSReloadResult" in s
        assert "pinned" in s
        assert "rate=" in s

    def test_repr_format(self):
        r = IPFSReloadResult(
            count=4,
            pin_results={"a": "Qm1", "b": "Qm2", "c": "Qm3", "d": None},
        )
        s = repr(r)
        # 3 succeeded / 4 total → 75.0%
        assert "3/4" in s
        assert "75.0%" in s

    def test_repr_all_success(self):
        r = IPFSReloadResult(
            count=3,
            pin_results={"a": "Qm1", "b": "Qm2", "c": "Qm3"},
        )
        s = repr(r)
        assert "3/3" in s
        assert "rate=100.0%" in s

    def test_repr_all_failed(self):
        r = IPFSReloadResult(
            count=2,
            pin_results={"a": None, "b": None},
        )
        s = repr(r)
        assert "0/2" in s
        assert "rate=0.0%" in s

    def test_repr_empty(self):
        r = IPFSReloadResult(count=0, pin_results={})
        s = repr(r)
        assert "0/0" in s

    def test_repr_is_str(self):
        r = IPFSReloadResult(count=1, pin_results={"x": "Qm0"})
        assert isinstance(repr(r), str)

    def test_repr_single_failed(self):
        r = IPFSReloadResult(count=4, pin_results={"a": "Q1", "b": "Q2", "c": "Q3", "d": None})
        s = repr(r)
        assert "3/4" in s

    def test_repr_half_failed(self):
        r = IPFSReloadResult(count=2, pin_results={"a": "Q1", "b": None})
        s = repr(r)
        assert "1/2" in s
        assert "rate=50.0%" in s


# ---------------------------------------------------------------------------
# 3. PubSubBus.handler_topics
# ---------------------------------------------------------------------------

class TestPubSubBusHandlerTopics:
    def _bus(self):
        return PubSubBus()

    def test_handler_topics_empty(self):
        bus = self._bus()
        def cb(t, p): pass
        assert bus.handler_topics(cb) == []

    def test_handler_topics_single(self):
        bus = self._bus()
        def cb(t, p): pass
        bus.subscribe("receipts", cb)
        assert bus.handler_topics(cb) == ["receipts"]

    def test_handler_topics_multiple(self):
        bus = self._bus()
        def cb(t, p): pass
        bus.subscribe("receipts", cb)
        bus.subscribe("audit", cb)
        result = bus.handler_topics(cb)
        assert sorted(result) == ["audit", "receipts"]

    def test_handler_topics_sorted(self):
        bus = self._bus()
        def cb(t, p): pass
        bus.subscribe("z_topic", cb)
        bus.subscribe("a_topic", cb)
        bus.subscribe("m_topic", cb)
        result = bus.handler_topics(cb)
        assert result == sorted(result)

    def test_handler_topics_not_affecting_others(self):
        bus = self._bus()
        def cb1(t, p): pass
        def cb2(t, p): pass
        bus.subscribe("receipts", cb1)
        bus.subscribe("audit", cb2)
        assert bus.handler_topics(cb1) == ["receipts"]
        assert bus.handler_topics(cb2) == ["audit"]

    def test_handler_topics_after_unsubscribe(self):
        bus = self._bus()
        def cb(t, p): pass
        bus.subscribe("receipts", cb)
        bus.subscribe("audit", cb)
        bus.unsubscribe("receipts", cb)
        assert bus.handler_topics(cb) == ["audit"]

    def test_handler_topics_returns_list(self):
        bus = self._bus()
        def cb(t, p): pass
        assert isinstance(bus.handler_topics(cb), list)

    def test_handler_topics_after_clear_topic(self):
        bus = self._bus()
        def cb(t, p): pass
        bus.subscribe("receipts", cb)
        bus.subscribe("audit", cb)
        bus.clear_topic("receipts")
        assert bus.handler_topics(cb) == ["audit"]

    def test_handler_topics_after_clear_all(self):
        bus = self._bus()
        def cb(t, p): pass
        bus.subscribe("receipts", cb)
        bus.subscribe("audit", cb)
        bus.clear_all()
        assert bus.handler_topics(cb) == []

    def test_handler_topics_lambda(self):
        bus = self._bus()
        cb = lambda t, p: None
        bus.subscribe("x", cb)
        assert bus.handler_topics(cb) == ["x"]


# ---------------------------------------------------------------------------
# 4. ComplianceChecker.backup_age
# ---------------------------------------------------------------------------

class TestComplianceCheckerBackupAge:
    def test_backup_age_no_backup(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            assert ComplianceChecker.backup_age(path) is None

    def test_backup_age_with_bak(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            open(path + ".bak", "w").close()
            age = ComplianceChecker.backup_age(path)
            assert age is not None
            assert isinstance(age, float)

    def test_backup_age_is_mtime(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            bak = path + ".bak"
            open(bak, "w").close()
            expected = os.path.getmtime(bak)
            assert ComplianceChecker.backup_age(path) == pytest.approx(expected)

    def test_backup_age_primary_bak_used(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            bak0 = path + ".bak"
            bak1 = path + ".bak.1"
            open(bak0, "w").close()
            open(bak1, "w").close()
            # Should use bak0 (index 0 = primary)
            expected = os.path.getmtime(bak0)
            assert ComplianceChecker.backup_age(path) == pytest.approx(expected)

    def test_backup_age_returns_none_for_missing(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "nofile.enc")
            result = ComplianceChecker.backup_age(path)
            assert result is None

    def test_backup_age_static_method(self):
        # Can be called on the class
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            result = ComplianceChecker.backup_age(path)
            assert result is None

    def test_backup_age_after_rotate(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            open(path + ".bak", "w").close()
            ComplianceChecker.rotate_bak(path, max_keep=3)
            # After rotate, .bak still exists (was renamed to .bak.1)
            # backup_age checks .bak first (list_bak_files[0])
            files = ComplianceChecker.list_bak_files(path)
            if files:
                age = ComplianceChecker.backup_age(path)
                assert age is not None

    def test_backup_age_after_purge(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            open(path + ".bak", "w").close()
            ComplianceChecker.purge_bak_files(path)
            assert ComplianceChecker.backup_age(path) is None


# ---------------------------------------------------------------------------
# 5. E2E: diagnostics / health-check scenario
# ---------------------------------------------------------------------------

class TestE2ESession77:
    def test_merge_result_repr_roundtrip(self):
        r = MergeResult(added_count=5, conflict_count=2, revocations_copied=1)
        s = repr(r)
        assert "added=5" in s
        assert "conflicts=2" in s
        # import_rate = 5/7 ≈ 71.4%
        assert "71.4%" in s

    def test_ipfs_result_repr_roundtrip(self):
        r = IPFSReloadResult(count=5, pin_results={
            "a": "Q1", "b": "Q2", "c": "Q3", "d": None, "e": None
        })
        s = repr(r)
        assert "3/5" in s
        assert "60.0%" in s

    def test_handler_topics_health_check(self):
        bus = PubSubBus()
        def metrics_cb(t, p): pass
        def audit_cb(t, p): pass
        bus.subscribe("delegation_add", metrics_cb)
        bus.subscribe("receipt_disseminate", metrics_cb)
        bus.subscribe("receipt_disseminate", audit_cb)

        # Health check: which topics is metrics_cb listening to?
        topics = bus.handler_topics(metrics_cb)
        assert "delegation_add" in topics
        assert "receipt_disseminate" in topics
        assert "audit_cb" not in topics

    def test_backup_age_workflow(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "policy.enc")
            # No backup yet
            assert ComplianceChecker.backup_age(path) is None
            # Create backup
            open(path + ".bak", "w").close()
            age = ComplianceChecker.backup_age(path)
            assert age is not None
            # Purge
            ComplianceChecker.purge_bak_files(path)
            assert ComplianceChecker.backup_age(path) is None

    def test_combined_diagnostics(self):
        """Combined diagnostics: repr + handler_topics + backup_age."""
        # MergeResult repr
        mr = MergeResult(10, 2, 5)
        assert "added=10" in repr(mr)
        # IPFSReloadResult repr
        ir = IPFSReloadResult(3, {"a": "Q1", "b": "Q2", "c": None})
        assert "2/3" in repr(ir)
        # PubSubBus handler_topics
        bus = PubSubBus()
        cb = lambda t, p: None
        bus.subscribe("t1", cb)
        bus.subscribe("t2", cb)
        assert len(bus.handler_topics(cb)) == 2
        # ComplianceChecker backup_age
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "f.enc")
            assert ComplianceChecker.backup_age(p) is None
