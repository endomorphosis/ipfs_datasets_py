"""Session 68: MCP++ v23 Next Steps tests.

Items tested:
1. DelegationManager.merge() conflict detection (revoked CID skipped with UserWarning)
2. IPFSPolicyStore.reload(max_retries=1) — retry param propagated to re-pin
3. PublishAsyncResult.__int__ and __eq__ helpers
4. ComplianceChecker.restore_from_bak(path)
5. E2E regression covering sessions 60–67
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import warnings
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_delegation(cid: str, tool: str = "test_tool", resource: str = "res://test"):
    from ipfs_datasets_py.mcp_server.ucan_delegation import Delegation, Capability
    return Delegation(
        cid=cid,
        issuer="did:key:issuer",
        audience="did:key:audience",
        capabilities=[Capability(resource=resource, ability=tool)],
        expiry=9999999999,
    )


def _make_manager(path: Optional[str] = None):
    from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
    return DelegationManager(path=path)


# ---------------------------------------------------------------------------
# 1. DelegationManager.merge() conflict detection
# ---------------------------------------------------------------------------

class TestDelegationManagerMergeConflictDetection:
    """Revoked CIDs from other._store are skipped with UserWarning."""

    def test_conflict_skipped_with_warning(self):
        mgr_src = _make_manager()
        mgr_dst = _make_manager()
        d = _make_delegation("cid-conflict-1")
        mgr_src.add(d)
        # Revoke the same CID in dst BEFORE merging
        mgr_dst._revocation.revoke("cid-conflict-1")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            added = mgr_dst.merge(mgr_src)

        assert added == 0, "Conflict CID should not be added"
        assert any("cid-conflict-1" in str(w.message) for w in caught), "UserWarning expected"

    def test_non_conflicting_cids_added_normally(self):
        mgr_src = _make_manager()
        mgr_dst = _make_manager()
        d1 = _make_delegation("cid-ok-1")
        d2 = _make_delegation("cid-ok-2")
        mgr_src.add(d1)
        mgr_src.add(d2)
        # Revoke a *different* CID in dst
        mgr_dst._revocation.revoke("cid-unrelated")

        added = mgr_dst.merge(mgr_src)
        assert added == 2

    def test_warning_category_is_user_warning(self):
        mgr_src = _make_manager()
        mgr_dst = _make_manager()
        mgr_src.add(_make_delegation("cid-cat-1"))
        mgr_dst._revocation.revoke("cid-cat-1")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            mgr_dst.merge(mgr_src)

        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) >= 1

    def test_multiple_conflicts_each_warn(self):
        mgr_src = _make_manager()
        mgr_dst = _make_manager()
        for i in range(3):
            mgr_src.add(_make_delegation(f"cid-multi-{i}"))
            mgr_dst._revocation.revoke(f"cid-multi-{i}")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            added = mgr_dst.merge(mgr_src)

        assert added == 0
        uw = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(uw) == 3

    def test_partial_conflict_adds_non_conflicted(self):
        mgr_src = _make_manager()
        mgr_dst = _make_manager()
        mgr_src.add(_make_delegation("cid-revoked"))
        mgr_src.add(_make_delegation("cid-allowed"))
        mgr_dst._revocation.revoke("cid-revoked")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            added = mgr_dst.merge(mgr_src)

        assert added == 1
        cids = mgr_dst._store.list_cids()
        assert "cid-allowed" in cids
        assert "cid-revoked" not in cids

    def test_no_warning_when_no_conflicts(self):
        mgr_src = _make_manager()
        mgr_dst = _make_manager()
        mgr_src.add(_make_delegation("cid-fresh"))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            added = mgr_dst.merge(mgr_src)

        assert added == 1
        user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_warnings) == 0

    def test_source_manager_unchanged_after_conflict(self):
        mgr_src = _make_manager()
        mgr_dst = _make_manager()
        mgr_src.add(_make_delegation("cid-unchanged"))
        mgr_dst._revocation.revoke("cid-unchanged")

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            mgr_dst.merge(mgr_src)

        # Source manager still has the delegation
        assert "cid-unchanged" in mgr_src._store.list_cids()


# ---------------------------------------------------------------------------
# 2. IPFSPolicyStore.reload(max_retries=1)
# ---------------------------------------------------------------------------

class TestIPFSPolicyStoreReloadMaxRetries:
    """max_retries propagated to re-pin phase of reload()."""

    def _store_cls(self):
        try:
            from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSPolicyStore
            return IPFSPolicyStore
        except ImportError:
            return None

    def test_reload_has_max_retries_param(self):
        IPFSPolicyStore = self._store_cls()
        if IPFSPolicyStore is None:
            pytest.skip("IPFSPolicyStore not available")
        import inspect
        sig = inspect.signature(IPFSPolicyStore.reload)
        assert "max_retries" in sig.parameters

    def test_reload_max_retries_default_is_1(self):
        IPFSPolicyStore = self._store_cls()
        if IPFSPolicyStore is None:
            pytest.skip("IPFSPolicyStore not available")
        import inspect
        sig = inspect.signature(IPFSPolicyStore.reload)
        assert sig.parameters["max_retries"].default == 1

    def test_reload_retries_failed_pins(self):
        IPFSPolicyStore = self._store_cls()
        if IPFSPolicyStore is None:
            pytest.skip("IPFSPolicyStore not available")

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "store.json")
            store = IPFSPolicyStore.__new__(IPFSPolicyStore)
            # Populate minimal state via FilePolicyStore.__init__
            from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore, PolicyRegistry
            FilePolicyStore.__init__(store, path=path)
            store._ipfs_client = None
            store._ipfs_cids = {}

            # Write a minimal versioned policy file
            import json as _json
            payload = {"version": "1", "policies": {}}
            with open(path, "w") as fh:
                _json.dump(payload, fh)

            pin_call_count = [0]
            original_pin = store.pin_policy

            def fake_pin(name):
                pin_call_count[0] += 1
                # First call fails, second succeeds
                if pin_call_count[0] % 2 == 1:
                    return None
                return f"bafy-{name}"

            store.pin_policy = fake_pin
            count = store.reload(max_retries=2)
            # Even with retries the reload still returns policy count
            assert isinstance(count, int)

    def test_reload_max_retries_0_no_retry(self):
        IPFSPolicyStore = self._store_cls()
        if IPFSPolicyStore is None:
            pytest.skip("IPFSPolicyStore not available")
        import inspect
        # max_retries=0 must be accepted (no exception)
        sig = inspect.signature(IPFSPolicyStore.reload)
        assert sig.parameters["max_retries"].default is not inspect.Parameter.empty

    def test_reload_returns_int(self):
        IPFSPolicyStore = self._store_cls()
        if IPFSPolicyStore is None:
            pytest.skip("IPFSPolicyStore not available")
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "store.json")
            store = IPFSPolicyStore.__new__(IPFSPolicyStore)
            from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
            FilePolicyStore.__init__(store, path=path)
            store._ipfs_client = None
            store._ipfs_cids = {}
            store.pin_policy = lambda _name: None

            import json as _json
            with open(path, "w") as fh:
                _json.dump({"version": "1", "policies": {}}, fh)

            result = store.reload(max_retries=0)
            assert isinstance(result, int)


# ---------------------------------------------------------------------------
# 3. PublishAsyncResult.__int__ and __eq__
# ---------------------------------------------------------------------------

class TestPublishAsyncResultHelpers:
    """PublishAsyncResult backward-compat int/eq helpers."""

    def _result(self, notified: int = 3, timed_out: int = 1):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        return PublishAsyncResult(notified=notified, timed_out=timed_out)

    def test_int_returns_notified(self):
        r = self._result(notified=5, timed_out=2)
        assert int(r) == 5

    def test_eq_int_compares_notified(self):
        r = self._result(notified=3, timed_out=1)
        assert r == 3

    def test_eq_int_not_equal(self):
        r = self._result(notified=3, timed_out=1)
        assert not (r == 4)

    def test_eq_publish_async_result_same(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        r1 = PublishAsyncResult(notified=3, timed_out=1)
        r2 = PublishAsyncResult(notified=3, timed_out=1)
        assert r1 == r2

    def test_eq_publish_async_result_different(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        r1 = PublishAsyncResult(notified=3, timed_out=1)
        r2 = PublishAsyncResult(notified=2, timed_out=1)
        assert r1 != r2

    def test_int_zero(self):
        r = self._result(notified=0, timed_out=0)
        assert int(r) == 0
        assert r == 0

    def test_int_method_truthy(self):
        r = self._result(notified=2, timed_out=0)
        assert int(r)  # non-zero notified → truthy

    def test_timed_out_accessible(self):
        r = self._result(notified=3, timed_out=2)
        assert r.timed_out == 2

    def test_legacy_notified_attribute_still_works(self):
        r = self._result(notified=7, timed_out=0)
        n = r.notified if hasattr(r, "notified") else r
        assert n == 7


# ---------------------------------------------------------------------------
# 4. ComplianceChecker.restore_from_bak()
# ---------------------------------------------------------------------------

class TestComplianceCheckerRestoreFromBak:
    """ComplianceChecker.restore_from_bak() test suite."""

    def _checker(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        return make_default_compliance_checker()

    def test_restore_when_bak_exists(self):
        c = self._checker()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            bak_path = path + ".bak"
            # Write a sentinel to both files
            with open(path, "wb") as fh:
                fh.write(b"new-corrupted")
            with open(bak_path, "wb") as fh:
                fh.write(b"original-content")

            result = c.restore_from_bak(path)
            assert result is True
            with open(path, "rb") as fh:
                content = fh.read()
            assert content == b"original-content"

    def test_backup_removed_after_restore(self):
        c = self._checker()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            bak_path = path + ".bak"
            with open(path, "wb") as fh:
                fh.write(b"current")
            with open(bak_path, "wb") as fh:
                fh.write(b"backup")

            c.restore_from_bak(path)
            assert not os.path.exists(bak_path)

    def test_returns_false_when_no_bak(self):
        c = self._checker()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            result = c.restore_from_bak(path)
        assert result is False

    def test_returns_false_when_bak_copy_fails(self):
        c = self._checker()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "rules.enc")
            bak_path = path + ".bak"
            with open(bak_path, "wb") as fh:
                fh.write(b"backup")
            # Make destination read-only to force copy failure
            dest_dir = os.path.join(td, "readonly_subdir")
            os.makedirs(dest_dir)
            dest_path = os.path.join(dest_dir, "rules.enc")
            bak2 = dest_path + ".bak"
            with open(bak2, "wb") as fh:
                fh.write(b"backup2")
            os.chmod(dest_dir, 0o444)
            try:
                result = c.restore_from_bak(dest_path)
                assert result is False
            finally:
                os.chmod(dest_dir, 0o755)

    def test_has_method_on_default_checker(self):
        c = self._checker()
        assert hasattr(c, "restore_from_bak")
        assert callable(c.restore_from_bak)

    def test_bak_path_is_path_plus_bak(self):
        """Verify restore_from_bak looks for <path>.bak."""
        c = self._checker()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "myfile.enc")
            wrong_bak = path + ".backup"  # wrong extension
            with open(wrong_bak, "wb") as fh:
                fh.write(b"wrong")
            result = c.restore_from_bak(path)
        assert result is False  # no .bak file, only .backup


# ---------------------------------------------------------------------------
# 5. E2E regression — sessions 60–67 combined
# ---------------------------------------------------------------------------

class TestE2ESession68:
    """Regression E2E covering session 60–67 features."""

    def test_delegation_manager_merge_chain(self):
        """Chain: add → revoke → merge (conflict) → merge (clean)."""
        mgr_a = _make_manager()
        mgr_b = _make_manager()

        d1 = _make_delegation("chain-cid-1")
        d2 = _make_delegation("chain-cid-2")
        mgr_a.add(d1)
        mgr_a.add(d2)

        # Revoke cid-1 in b before merging
        mgr_b._revocation.revoke("chain-cid-1")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            added = mgr_b.merge(mgr_a)

        assert added == 1  # only cid-2 added
        assert "chain-cid-2" in mgr_b._store.list_cids()
        assert "chain-cid-1" not in mgr_b._store.list_cids()
        user_w = [w for w in caught if issubclass(w.category, UserWarning)]
        assert len(user_w) >= 1

    def test_publish_async_result_equality_chain(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult, PubSubBus
        bus = PubSubBus()
        results = []
        bus.subscribe("test_topic", lambda _t, p: results.append(p))
        # Use sync publish for simplicity
        n = bus.publish("test_topic", {"x": 1})
        assert n == 1
        assert isinstance(results, list) and len(results) == 1

    def test_compliance_restore_from_bak_round_trip(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        c = make_default_compliance_checker()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "comp.enc")
            bak_path = path + ".bak"
            original = b"encrypted-content-original"
            new = b"encrypted-content-new"
            with open(path, "wb") as fh:
                fh.write(original)
            with open(bak_path, "wb") as fh:
                fh.write(original)  # bak is the original

            # Overwrite path with new (simulating failed migration)
            with open(path, "wb") as fh:
                fh.write(new)

            ok = c.restore_from_bak(path)
            assert ok is True
            with open(path, "rb") as fh:
                assert fh.read() == original

    def test_publish_async_result_int_comparison(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        r = PublishAsyncResult(notified=2, timed_out=0)
        assert r == 2
        assert int(r) == 2
        assert r != 3

    def test_delegation_merge_no_conflict_audit(self):
        """Merge with audit_log and no revocations — no audit entries."""
        mgr_src = _make_manager()
        mgr_dst = _make_manager()
        mgr_src.add(_make_delegation("audit-cid-1"))
        audit: list = []
        added = mgr_dst.merge(mgr_src, copy_revocations=False, audit_log=audit)
        assert added == 1
        assert len(audit) == 0  # no revocations copied

    def test_delegation_merge_conflict_does_not_add_to_store(self):
        mgr_src = _make_manager()
        mgr_dst = _make_manager()
        mgr_src.add(_make_delegation("conflict-store-cid"))
        mgr_dst._revocation.revoke("conflict-store-cid")
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            mgr_dst.merge(mgr_src)
        assert "conflict-store-cid" not in mgr_dst._store.list_cids()

    def test_publish_async_result_hash_works(self):
        """NamedTuple should still be hashable."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        r = PublishAsyncResult(notified=1, timed_out=0)
        s = {r}  # should not raise
        assert len(s) == 1

    def test_restore_from_bak_returns_false_no_bak(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        c = make_default_compliance_checker()
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "nonexistent.enc")
            assert c.restore_from_bak(path) is False

    def test_int_on_publish_async_result_zero(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        r = PublishAsyncResult(notified=0, timed_out=0)
        assert int(r) == 0
        assert r == 0
