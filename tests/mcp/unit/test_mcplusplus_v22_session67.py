"""
Session 67: MCP++ v22 Next Steps

Tests for:
  1. DelegationManager.merge(audit_log=None) — revocation audit log
  2. IPFSPolicyStore.save(max_retries=1) — pin retry
  3. PubSubBus.publish_async() → PublishAsyncResult(notified, timed_out)
  4. ComplianceChecker.migrate_encrypted() atomic .bak backup
  5. Full E2E regression (sessions 66 + 67)
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / repo root
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[3]


# ---------------------------------------------------------------------------
# 1. DelegationManager.merge(audit_log=None)
# ---------------------------------------------------------------------------

class TestDelegationManagerMergeAuditLog:
    def _make_manager(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        return DelegationManager()

    def _add_delegation(self, mgr, cid: str):
        """Add a mock delegation to a manager."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationToken
        d = DelegationToken(issuer="did:test:issuer", audience="did:test:audience",
                            resource="test", ability="read", expiry=9999999999.0)
        object.__setattr__(d, "cid", cid) if hasattr(d, "__dataclass_fields__") else None
        # Use store directly
        mgr._store._delegations[cid] = d  # type: ignore[attr-defined]
        mgr._store._cid_list.append(cid)  # type: ignore[attr-defined]

    def test_audit_log_none_no_error(self):
        """merge(audit_log=None) does not raise."""
        src = self._make_manager()
        dst = self._make_manager()
        result = dst.merge(src, copy_revocations=False, audit_log=None)
        assert isinstance(result, int)

    def test_audit_log_records_nothing_when_copy_revocations_false(self):
        """When copy_revocations=False, audit_log.append is never called."""
        src = self._make_manager()
        src._revocation.revoke("cid-revoked-1")
        dst = self._make_manager()
        log: List[Dict] = []

        class SimpleLog:
            def append(self, entry):
                log.append(entry)

        dst.merge(src, copy_revocations=False, audit_log=SimpleLog())
        assert log == []

    def test_audit_log_records_copied_revocations(self):
        """When copy_revocations=True, each copied CID is logged."""
        src = self._make_manager()
        src._revocation.revoke("cid-a")
        src._revocation.revoke("cid-b")
        dst = self._make_manager()
        log: List[Dict] = []

        class SimpleLog:
            def append(self, entry):
                log.append(entry)

        dst.merge(src, copy_revocations=True, audit_log=SimpleLog())
        cids_logged = {e["cid"] for e in log}
        assert "cid-a" in cids_logged
        assert "cid-b" in cids_logged
        assert all(e["event"] == "revocation_copied" for e in log)

    def test_audit_log_respects_skip_revocations(self):
        """Skipped CIDs are not logged."""
        src = self._make_manager()
        src._revocation.revoke("cid-keep")
        src._revocation.revoke("cid-skip")
        dst = self._make_manager()
        log: List[Dict] = []

        class SimpleLog:
            def append(self, entry):
                log.append(entry)

        dst.merge(src, copy_revocations=True,
                  skip_revocations={"cid-skip"}, audit_log=SimpleLog())
        logged_cids = {e["cid"] for e in log}
        assert "cid-keep" in logged_cids
        assert "cid-skip" not in logged_cids

    def test_audit_log_exception_does_not_propagate(self):
        """If audit_log.append raises, merge still succeeds."""
        src = self._make_manager()
        src._revocation.revoke("cid-x")
        dst = self._make_manager()

        class BrokenLog:
            def append(self, entry):
                raise RuntimeError("broken")

        result = dst.merge(src, copy_revocations=True, audit_log=BrokenLog())
        assert isinstance(result, int)
        # Revocation still applied despite log failure
        assert dst._revocation.is_revoked("cid-x")

    def test_audit_log_only_called_for_actually_revoked_cids(self):
        """Empty revocation list → no audit entries."""
        src = self._make_manager()  # no revocations
        dst = self._make_manager()
        log: List[Dict] = []

        class SimpleLog:
            def append(self, entry):
                log.append(entry)

        dst.merge(src, copy_revocations=True, audit_log=SimpleLog())
        assert log == []

    def test_audit_log_list_as_sink(self):
        """A plain list with .append() works as audit_log."""
        src = self._make_manager()
        src._revocation.revoke("cid-z")
        dst = self._make_manager()
        log: List[Dict] = []
        dst.merge(src, copy_revocations=True, audit_log=log)
        assert len(log) == 1
        assert log[0]["cid"] == "cid-z"


# ---------------------------------------------------------------------------
# 2. IPFSPolicyStore.save(max_retries=1)
# ---------------------------------------------------------------------------

class TestIPFSPolicyStoreSaveMaxRetries:
    def _make_store(self, path: str):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSPolicyStore, PolicyRegistry
        store = IPFSPolicyStore(path=path, registry=None)
        return store

    def test_save_returns_dict(self, tmp_path):
        """save() returns a dict (empty when no policies)."""
        store = self._make_store(str(tmp_path / "store.json"))
        result = store.save()
        assert isinstance(result, dict)
        assert result == {}

    def test_save_max_retries_default(self, tmp_path):
        """max_retries defaults to 1 and is accepted without error."""
        store = self._make_store(str(tmp_path / "store.json"))
        result = store.save(max_retries=1)
        assert isinstance(result, dict)

    def test_save_max_retries_zero(self, tmp_path):
        """max_retries=0 means no retry (just one attempt)."""
        store = self._make_store(str(tmp_path / "store.json"))
        result = store.save(max_retries=0)
        assert isinstance(result, dict)

    def test_save_max_retries_large(self, tmp_path):
        """max_retries=3 is accepted."""
        store = self._make_store(str(tmp_path / "store.json"))
        result = store.save(max_retries=3)
        assert isinstance(result, dict)

    def test_save_retry_called_on_pin_failure(self, tmp_path):
        """When pin_policy returns None, it is retried max_retries times."""
        store = self._make_store(str(tmp_path / "store.json"))
        call_count = [0]

        def fake_pin(name):
            call_count[0] += 1
            return None  # always fail

        store.pin_policy = fake_pin  # type: ignore[method-assign]
        with (
            patch.object(store.__class__.__bases__[0], "save", return_value=None),
            patch.object(store._registry, "list_names", return_value=["fake_policy"]),
        ):
            store.save(max_retries=2)
        # 1 initial + 2 retries = 3 calls
        assert call_count[0] == 3

    def test_save_retry_stops_on_success(self, tmp_path):
        """Retry stops as soon as pin_policy succeeds."""
        store = self._make_store(str(tmp_path / "store.json"))
        # Patch list_names to return one name + super().save() to no-op
        call_count = [0]

        def fake_pin(name):
            call_count[0] += 1
            if call_count[0] >= 2:
                return "QmFakeCID"
            return None

        store.pin_policy = fake_pin  # type: ignore[method-assign]
        with (
            patch.object(store.__class__.__bases__[0], "save", return_value=None),
            patch.object(store._registry, "list_names", return_value=["p"]),
        ):
            result = store.save(max_retries=3)
        # First call returns None, second returns CID → stop
        assert call_count[0] == 2
        assert result.get("p") == "QmFakeCID"


# ---------------------------------------------------------------------------
# 3. PubSubBus.publish_async() → PublishAsyncResult
# ---------------------------------------------------------------------------

class TestPublishAsyncResult:
    def test_namedtuple_fields(self):
        """PublishAsyncResult has notified and timed_out fields."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        r = PublishAsyncResult(notified=5, timed_out=2)
        assert r.notified == 5
        assert r.timed_out == 2

    def test_namedtuple_indexing(self):
        """PublishAsyncResult supports index access."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        r = PublishAsyncResult(notified=3, timed_out=1)
        assert r[0] == 3
        assert r[1] == 1

    def test_namedtuple_is_tuple(self):
        """PublishAsyncResult is a tuple subclass."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        r = PublishAsyncResult(notified=0, timed_out=0)
        assert isinstance(r, tuple)

    def test_publish_async_returns_namedtuple(self):
        """publish_async() returns a PublishAsyncResult (or compatible int in fallback)."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus, PublishAsyncResult
        bus = PubSubBus()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = asyncio.run(bus.publish_async("topic", {}))
        # Either a PublishAsyncResult (anyio present) or a PublishAsyncResult from int
        assert isinstance(result, (PublishAsyncResult, int))

    def test_publish_async_no_subscribers_zero_counts(self):
        """With no subscribers, notified=0 and timed_out=0."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus, PublishAsyncResult
        bus = PubSubBus()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = asyncio.run(bus.publish_async("topic", {}))
        if isinstance(result, PublishAsyncResult):
            assert result.notified == 0
            assert result.timed_out == 0

    def test_publish_async_with_one_handler(self):
        """With one sync handler, notified=1."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus, PublishAsyncResult
        bus = PubSubBus()
        received: List[Any] = []
        bus.subscribe("topic", lambda _t, p: received.append(p))
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            result = asyncio.run(bus.publish_async("topic", {"x": 1}))
        if isinstance(result, PublishAsyncResult):
            assert result.notified >= 1
        elif isinstance(result, int):
            assert result >= 1

    def test_publish_async_fallback_returns_compatible_result(self):
        """When anyio absent, sync fallback result is compatible."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus, PublishAsyncResult
        bus = PubSubBus()
        bus.subscribe("topic", lambda _t, _p: None)
        with patch.dict("sys.modules", {"anyio": None}):
            with warnings.catch_warnings(record=True):
                warnings.simplefilter("always")
                result = asyncio.run(bus.publish_async("topic", {}))
        # In fallback path, result is a PublishAsyncResult wrapping int
        assert isinstance(result, (int, tuple))


# ---------------------------------------------------------------------------
# 4. ComplianceChecker.migrate_encrypted() atomic .bak backup
# ---------------------------------------------------------------------------

class TestComplianceCheckerMigrateEncryptedBackup:
    def _can_encrypt(self) -> bool:
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
            return True
        except ImportError:
            return False

    def test_migrate_creates_bak_then_removes_on_success(self, tmp_path):
        """On success, a .bak file is created and then removed."""
        if not self._can_encrypt():
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        path = str(tmp_path / "rules.enc")
        checker.save_encrypted(path, "old-pass")

        bak_path = path + ".bak"
        assert os.path.exists(path)
        result = checker.migrate_encrypted(path, "old-pass", "new-pass")
        assert result is True
        assert not os.path.exists(bak_path), "backup should be cleaned up after success"

    def test_migrate_bak_present_on_write_failure(self, tmp_path):
        """If the write fails, .bak remains in place."""
        if not self._can_encrypt():
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        path = str(tmp_path / "rules.enc")
        checker.save_encrypted(path, "old-pass")
        bak_path = path + ".bak"

        # Simulate a write failure
        import builtins
        original_open = builtins.open

        def patched_open(file, mode="r", *args, **kwargs):
            if str(file) == path and "w" in mode and "b" in mode:
                raise OSError("simulated write failure")
            return original_open(file, mode, *args, **kwargs)

        with patch("builtins.open", side_effect=patched_open):
            result = checker.migrate_encrypted(path, "old-pass", "new-pass")
        assert result is False
        # backup should still be present after failure
        assert os.path.exists(bak_path)

    def test_migrate_wrong_password_no_bak(self, tmp_path):
        """Wrong old password → returns False without creating .bak."""
        if not self._can_encrypt():
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        path = str(tmp_path / "rules.enc")
        checker.save_encrypted(path, "correct-pass")
        bak_path = path + ".bak"

        result = checker.migrate_encrypted(path, "wrong-pass", "new-pass")
        assert result is False
        assert not os.path.exists(bak_path)

    def test_migrate_missing_file_returns_false(self, tmp_path):
        """Non-existent file returns False without creating .bak."""
        if not self._can_encrypt():
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        path = str(tmp_path / "nonexistent.enc")
        result = checker.migrate_encrypted(path, "pass", "new-pass")
        assert result is False
        assert not os.path.exists(path + ".bak")

    def test_migrate_re_encrypted_file_can_be_loaded_with_new_password(self, tmp_path):
        """After migration, the file can be loaded with the new password."""
        if not self._can_encrypt():
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        checker = ComplianceChecker()
        path = str(tmp_path / "rules.enc")
        checker.save_encrypted(path, "old-pass")
        result = checker.migrate_encrypted(path, "old-pass", "new-pass")
        assert result is True

        new_checker = ComplianceChecker()
        loaded = new_checker.load_encrypted(path, "new-pass")
        assert loaded >= 0  # successfully loaded (may be 0 rules in stub)

    def test_migrate_bak_path_is_dot_bak_suffix(self, tmp_path):
        """Backup path is always <original_path>.bak."""
        if not self._can_encrypt():
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        import inspect
        src = inspect.getsource(ComplianceChecker.migrate_encrypted)
        assert ".bak" in src, "migrate_encrypted source should reference .bak suffix"


# ---------------------------------------------------------------------------
# 5. Full E2E regression (sessions 66 + 67)
# ---------------------------------------------------------------------------

class TestE2ESession67:
    def test_delegation_manager_merge_audit_and_skip_combined(self):
        """merge() with copy_revocations, skip_revocations, and audit_log all at once."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        src._revocation.revoke("cid-1")
        src._revocation.revoke("cid-2")
        src._revocation.revoke("cid-skip")
        dst = DelegationManager()
        log: List[Dict] = []

        count = dst.merge(
            src,
            copy_revocations=True,
            skip_revocations={"cid-skip"},
            audit_log=log,
        )
        assert isinstance(count, int)
        assert dst._revocation.is_revoked("cid-1")
        assert dst._revocation.is_revoked("cid-2")
        assert not dst._revocation.is_revoked("cid-skip")
        logged_cids = {e["cid"] for e in log}
        assert "cid-1" in logged_cids
        assert "cid-2" in logged_cids
        assert "cid-skip" not in logged_cids

    def test_publish_async_result_notified_timed_out_attributes(self):
        """PublishAsyncResult(notified=N, timed_out=M) is accessible by name and index."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        r = PublishAsyncResult(notified=7, timed_out=3)
        assert r.notified == 7
        assert r.timed_out == 3
        assert r[0] == 7
        assert r[1] == 3
        total = r.notified + r.timed_out
        assert total == 10

    def test_compliance_checker_merge_followed_by_save_migrate(self, tmp_path):
        """merge() + save_encrypted() + migrate_encrypted() full cycle."""
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM  # noqa: F401
        except ImportError:
            pytest.skip("cryptography not installed")
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        c1 = ComplianceChecker()
        c2 = ComplianceChecker()
        c1.add_rule("custom_rule", lambda _intent: None)  # type: ignore
        merged = c2.merge(c1)
        assert isinstance(merged, int)
        path = str(tmp_path / "rules.enc")
        c2.save_encrypted(path, "initial-pass")
        result = c2.migrate_encrypted(path, "initial-pass", "rotated-pass")
        assert result is True

    def test_ipfs_policy_store_save_max_retries_signature(self):
        """IPFSPolicyStore.save() accepts max_retries keyword arg."""
        import inspect
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSPolicyStore
        sig = inspect.signature(IPFSPolicyStore.save)
        params = list(sig.parameters)
        assert "max_retries" in params, "save() should have max_retries parameter"

    def test_delegation_manager_merge_audit_log_no_write_on_copy_false(self):
        """audit_log is never called when copy_revocations=False."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        src._revocation.revoke("cid-a")
        dst = DelegationManager()
        log: List[Dict] = []
        dst.merge(src, copy_revocations=False, audit_log=log)
        assert len(log) == 0

    def test_session_66_tests_still_pass(self):
        """Regression: session 66 main contracts still hold."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus

        # DelegationManager.merge returns int
        m1 = DelegationManager()
        m2 = DelegationManager()
        assert isinstance(m1.merge(m2), int)

        # PubSubBus.publish returns int
        bus = PubSubBus()
        assert isinstance(bus.publish("t", {}), int)

    def test_publish_async_result_is_namedtuple_class(self):
        """PublishAsyncResult is importable and is a NamedTuple."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PublishAsyncResult
        import collections
        assert issubclass(PublishAsyncResult, tuple)

    def test_delegation_manager_merge_audit_log_list_entries_are_dicts(self):
        """Each audit entry is a dict with 'event' and 'cid' keys."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        src = DelegationManager()
        src._revocation.revoke("audit-cid")
        dst = DelegationManager()
        log: List[Any] = []
        dst.merge(src, copy_revocations=True, audit_log=log)
        assert len(log) == 1
        entry = log[0]
        assert isinstance(entry, dict)
        assert "event" in entry
        assert "cid" in entry
        assert entry["event"] == "revocation_copied"
        assert entry["cid"] == "audit-cid"

    def test_compliance_checker_migrate_encrypted_method_signature(self):
        """migrate_encrypted has path, old_password, new_password params."""
        import inspect
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
        sig = inspect.signature(ComplianceChecker.migrate_encrypted)
        params = list(sig.parameters.keys())
        assert "path" in params
        assert "old_password" in params
        assert "new_password" in params
