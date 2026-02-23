"""Session 76 — MCP++ v31 Next Steps

Tests for:
1. MergeResult.from_dict()          (ucan_delegation.py)
2. IPFSReloadResult.from_dict()     (nl_ucan_policy.py)
3. PubSubBus.snapshot()             (mcp_p2p_transport.py)
4. ComplianceChecker.backup_count() (compliance_checker.py)
5. E2E: round-trips + monitoring scenario
"""

import os
import tempfile
import pytest

# ---------------------------------------------------------------------------
# Imports (guarded so the test module can still be collected even when some
# optional dependency is absent)
# ---------------------------------------------------------------------------

try:
    from ipfs_datasets_py.mcp_server.ucan_delegation import (
        MergeResult,
        DelegationManager,
    )
    _DELEGATION_AVAILABLE = True
except Exception:
    _DELEGATION_AVAILABLE = False

try:
    from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSReloadResult
    _IPFS_RELOAD_AVAILABLE = True
except Exception:
    _IPFS_RELOAD_AVAILABLE = False

try:
    from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
    _PUBSUB_AVAILABLE = True
except Exception:
    _PUBSUB_AVAILABLE = False

try:
    from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
    _COMPLIANCE_AVAILABLE = True
except Exception:
    _COMPLIANCE_AVAILABLE = False

pytestmark = pytest.mark.unit


# ===========================================================================
# 1. MergeResult.from_dict()
# ===========================================================================

@pytest.mark.skipif(not _DELEGATION_AVAILABLE, reason="ucan_delegation unavailable")
class TestMergeResultFromDict:
    """MergeResult.from_dict() — round-trip and edge cases."""

    def test_from_dict_round_trip_basic(self):
        """to_dict / from_dict round-trip preserves all fields."""
        original = MergeResult(added_count=3, conflict_count=1, revocations_copied=2)
        restored = MergeResult.from_dict(original.to_dict())
        assert restored.added_count == 3
        assert restored.conflict_count == 1
        assert restored.revocations_copied == 2

    def test_from_dict_equality(self):
        """Round-tripped instance has identical fields to the original."""
        r = MergeResult(added_count=5, conflict_count=0, revocations_copied=0)
        restored = MergeResult.from_dict(r.to_dict())
        assert restored.added_count == r.added_count
        assert restored.conflict_count == r.conflict_count
        assert restored.revocations_copied == r.revocations_copied

    def test_from_dict_import_rate_preserved(self):
        """Derived import_rate is correct after round-trip."""
        r = MergeResult(added_count=3, conflict_count=1)
        restored = MergeResult.from_dict(r.to_dict())
        assert restored.import_rate == pytest.approx(0.75)

    def test_from_dict_zero_counts(self):
        """Empty result survives round-trip."""
        r = MergeResult(added_count=0, conflict_count=0, revocations_copied=0)
        restored = MergeResult.from_dict(r.to_dict())
        assert restored.added_count == 0
        assert restored.conflict_count == 0
        assert restored.import_rate == 0.0

    def test_from_dict_ignores_import_rate_key(self):
        """import_rate key in dict is silently ignored (derived property)."""
        d = {"added": 2, "conflicts": 2, "revocations_copied": 0, "import_rate": 0.999}
        r = MergeResult.from_dict(d)
        # import_rate is recalculated, not read from dict
        assert r.import_rate == pytest.approx(0.5)

    def test_from_dict_missing_keys_default_to_zero(self):
        """Missing keys default to 0."""
        r = MergeResult.from_dict({})
        assert r.added_count == 0
        assert r.conflict_count == 0
        assert r.revocations_copied == 0

    def test_from_dict_partial_keys(self):
        """Only 'added' present — others default."""
        r = MergeResult.from_dict({"added": 7})
        assert r.added_count == 7
        assert r.conflict_count == 0
        assert r.revocations_copied == 0

    def test_from_dict_returns_merge_result_type(self):
        """Return type is MergeResult."""
        r = MergeResult.from_dict({"added": 1, "conflicts": 0, "revocations_copied": 0})
        assert isinstance(r, MergeResult)


# ===========================================================================
# 2. IPFSReloadResult.from_dict()
# ===========================================================================

@pytest.mark.skipif(not _IPFS_RELOAD_AVAILABLE, reason="nl_ucan_policy unavailable")
class TestIPFSReloadResultFromDict:
    """IPFSReloadResult.from_dict() — round-trip semantics."""

    def _make_result(self, total=4, failures=1) -> "IPFSReloadResult":
        pin_results = {f"p{i}": f"Qm{i:040d}" for i in range(total - failures)}
        for i in range(failures):
            pin_results[f"fail_{i}"] = None
        return IPFSReloadResult(count=total, pin_results=pin_results)

    def test_from_dict_count_preserved(self):
        """count field is preserved through to_dict/from_dict."""
        r = self._make_result(total=4, failures=1)
        restored = IPFSReloadResult.from_dict(r.to_dict())
        assert restored.count == 4

    def test_from_dict_failed_count_preserved(self):
        """total_failed is correct after round-trip."""
        r = self._make_result(total=4, failures=1)
        restored = IPFSReloadResult.from_dict(r.to_dict())
        assert restored.total_failed == 1

    def test_from_dict_succeeded_count_preserved(self):
        """succeeded = count - total_failed."""
        r = self._make_result(total=4, failures=1)
        restored = IPFSReloadResult.from_dict(r.to_dict())
        assert restored.count - restored.total_failed == 3

    def test_from_dict_success_rate(self):
        """success_rate matches original."""
        r = self._make_result(total=4, failures=1)
        restored = IPFSReloadResult.from_dict(r.to_dict())
        assert restored.success_rate == pytest.approx(r.success_rate)

    def test_from_dict_all_succeeded(self):
        """all_succeeded=True when no failures."""
        r = self._make_result(total=3, failures=0)
        restored = IPFSReloadResult.from_dict(r.to_dict())
        assert restored.all_succeeded is True

    def test_from_dict_empty_result(self):
        """Empty reload (count=0) survives round-trip."""
        r = IPFSReloadResult(count=0, pin_results={})
        restored = IPFSReloadResult.from_dict(r.to_dict())
        assert restored.count == 0
        assert restored.total_failed == 0
        assert restored.success_rate == pytest.approx(1.0)

    def test_from_dict_returns_correct_type(self):
        """Return value is an IPFSReloadResult."""
        r = self._make_result(2, 0)
        restored = IPFSReloadResult.from_dict(r.to_dict())
        assert isinstance(restored, IPFSReloadResult)

    def test_from_dict_missing_count_defaults_zero(self):
        """Missing 'count' key → count=0."""
        r = IPFSReloadResult.from_dict({})
        assert r.count == 0


# ===========================================================================
# 3. PubSubBus.snapshot()
# ===========================================================================

@pytest.mark.skipif(not _PUBSUB_AVAILABLE, reason="mcp_p2p_transport unavailable")
class TestPubSubBusSnapshot:
    """PubSubBus.snapshot() — health-check endpoint helper."""

    def _bus(self):
        return PubSubBus()

    def test_snapshot_empty_bus(self):
        """Empty bus → empty dict."""
        bus = self._bus()
        assert bus.snapshot() == {}

    def test_snapshot_single_topic(self):
        """One subscriber → topic appears with count 1."""
        bus = self._bus()
        bus.subscribe("topic_a", lambda _t, _p: None)
        snap = bus.snapshot()
        assert "topic_a" in snap
        assert snap["topic_a"] == 1

    def test_snapshot_multiple_handlers_same_topic(self):
        """Two subscribers on same topic → count 2."""
        bus = self._bus()
        bus.subscribe("topic_a", lambda _t, _p: None)
        bus.subscribe("topic_a", lambda _t, _p: None)
        snap = bus.snapshot()
        assert snap["topic_a"] == 2

    def test_snapshot_multiple_topics(self):
        """Multiple topics each appear with correct counts."""
        bus = self._bus()
        bus.subscribe("alpha", lambda _t, _p: None)
        bus.subscribe("alpha", lambda _t, _p: None)
        bus.subscribe("beta", lambda _t, _p: None)
        snap = bus.snapshot()
        assert snap["alpha"] == 2
        assert snap["beta"] == 1

    def test_snapshot_excludes_empty_topics(self):
        """Topic with 0 subscribers not included."""
        bus = self._bus()
        bus.subscribe("topic_a", lambda _t, _p: None)
        sid = bus.subscribe("topic_b", lambda _t, _p: None)
        bus.unsubscribe_by_id(sid)
        snap = bus.snapshot()
        assert "topic_b" not in snap
        assert "topic_a" in snap

    def test_snapshot_after_clear_all(self):
        """After clear_all(), snapshot is empty."""
        bus = self._bus()
        bus.subscribe("x", lambda _t, _p: None)
        bus.clear_all()
        assert bus.snapshot() == {}

    def test_snapshot_after_clear_topic(self):
        """After clearing one topic, it disappears from snapshot."""
        bus = self._bus()
        bus.subscribe("x", lambda _t, _p: None)
        bus.subscribe("y", lambda _t, _p: None)
        bus.clear_topic("x")
        snap = bus.snapshot()
        assert "x" not in snap
        assert "y" in snap

    def test_snapshot_returns_dict_type(self):
        """Return type is dict."""
        bus = self._bus()
        assert isinstance(bus.snapshot(), dict)

    def test_snapshot_consistent_with_topics(self):
        """Keys in snapshot == set returned by topics()."""
        bus = self._bus()
        bus.subscribe("a", lambda _t, _p: None)
        bus.subscribe("b", lambda _t, _p: None)
        snap = bus.snapshot()
        assert set(snap.keys()) == set(bus.topics())

    def test_snapshot_consistent_with_subscription_count(self):
        """Sum of snapshot values == subscription_count()."""
        bus = self._bus()
        bus.subscribe("a", lambda _t, _p: None)
        bus.subscribe("a", lambda _t, _p: None)
        bus.subscribe("b", lambda _t, _p: None)
        snap = bus.snapshot()
        assert sum(snap.values()) == bus.subscription_count()


# ===========================================================================
# 4. ComplianceChecker.backup_count()
# ===========================================================================

@pytest.mark.skipif(not _COMPLIANCE_AVAILABLE, reason="compliance_checker unavailable")
class TestComplianceCheckerBackupCount:
    """ComplianceChecker.backup_count() — counts backup files."""

    def test_backup_count_no_backups(self):
        """Returns 0 when no backups exist."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.enc")
            assert ComplianceChecker.backup_count(path) == 0

    def test_backup_count_single_bak(self):
        """Returns 1 when only .bak exists."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.enc")
            open(path + ".bak", "w").close()
            assert ComplianceChecker.backup_count(path) == 1

    def test_backup_count_two_baks(self):
        """Returns 2 when .bak and .bak.1 both exist."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.enc")
            open(path + ".bak", "w").close()
            open(path + ".bak.1", "w").close()
            assert ComplianceChecker.backup_count(path) == 2

    def test_backup_count_three_baks(self):
        """Returns 3 for .bak, .bak.1, .bak.2."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.enc")
            for suffix in [".bak", ".bak.1", ".bak.2"]:
                open(path + suffix, "w").close()
            assert ComplianceChecker.backup_count(path) == 3

    def test_backup_count_equals_len_list_bak_files(self):
        """backup_count == len(list_bak_files(path)) invariant."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.enc")
            open(path + ".bak", "w").close()
            open(path + ".bak.1", "w").close()
            assert ComplianceChecker.backup_count(path) == len(
                ComplianceChecker.list_bak_files(path)
            )

    def test_backup_count_returns_int(self):
        """Return type is int."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.enc")
            assert isinstance(ComplianceChecker.backup_count(path), int)

    def test_backup_count_stops_at_gap(self):
        """Stops at gap: .bak.1 missing → .bak.2 not counted (gap stop)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.enc")
            # Only .bak and .bak.2 — no .bak.1 — list_bak_files stops at gap
            open(path + ".bak", "w").close()
            open(path + ".bak.2", "w").close()
            # .bak exists (count 1), .bak.1 missing → stop → count = 1
            assert ComplianceChecker.backup_count(path) == 1

    def test_backup_count_after_purge(self):
        """Returns 0 after purge."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.enc")
            open(path + ".bak", "w").close()
            ComplianceChecker.purge_bak_files(path)
            assert ComplianceChecker.backup_count(path) == 0


# ===========================================================================
# 5. E2E — round-trips + monitoring
# ===========================================================================

@pytest.mark.skipif(
    not (_DELEGATION_AVAILABLE and _IPFS_RELOAD_AVAILABLE
         and _PUBSUB_AVAILABLE and _COMPLIANCE_AVAILABLE),
    reason="one or more modules unavailable",
)
class TestE2ESession76:
    """End-to-end scenario exercising from_dict round-trips, snapshot, backup_count."""

    def test_merge_result_round_trip_via_json(self):
        """MergeResult survives JSON serialisation + from_dict."""
        import json
        r = MergeResult(added_count=4, conflict_count=2, revocations_copied=1)
        restored = MergeResult.from_dict(json.loads(json.dumps(r.to_dict())))
        assert restored.added_count == 4
        assert restored.conflict_count == 2
        assert restored.revocations_copied == 1

    def test_ipfs_reload_result_round_trip_via_json(self):
        """IPFSReloadResult count survives JSON serialisation + from_dict."""
        import json
        r = IPFSReloadResult(
            count=3,
            pin_results={"a": "Qm1", "b": "Qm2", "c": None},
        )
        d = json.loads(json.dumps(r.to_dict()))
        restored = IPFSReloadResult.from_dict(d)
        assert restored.count == 3
        assert restored.total_failed == 1

    def test_pubsub_snapshot_monitoring_scenario(self):
        """snapshot() provides consistent health info for a monitoring call."""
        bus = PubSubBus()
        bus.subscribe("metrics", lambda _t, _p: None)
        bus.subscribe("metrics", lambda _t, _p: None)
        bus.subscribe("alerts", lambda _t, _p: None)

        snap = bus.snapshot()
        # Both topics visible
        assert snap.get("metrics") == 2
        assert snap.get("alerts") == 1
        # Total matches subscription_count
        assert sum(snap.values()) == bus.subscription_count()

    def test_backup_count_workflow(self):
        """backup_count tracks the backup history lifecycle."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rules.enc")
            assert ComplianceChecker.backup_count(path) == 0

            # Create backups
            open(path + ".bak", "w").close()
            assert ComplianceChecker.backup_count(path) == 1

            open(path + ".bak.1", "w").close()
            assert ComplianceChecker.backup_count(path) == 2

            # Purge
            ComplianceChecker.purge_bak_files(path)
            assert ComplianceChecker.backup_count(path) == 0

    def test_merge_result_from_dict_classmethod_callable(self):
        """from_dict is a classmethod and not an instance method."""
        # callable directly on the class
        result = MergeResult.from_dict({"added": 1, "conflicts": 0, "revocations_copied": 0})
        assert isinstance(result, MergeResult)
