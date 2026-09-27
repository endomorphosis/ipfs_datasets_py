"""Durable registration intents, with no package I/O in the queue path."""
import threading

import pytest

from ipfs_datasets_py.duckdb_control import source_corpus_catalog as catalog
from tests.unit.duckdb_control.test_source_corpus_catalog import (
    _package, _register, _no_resolver, offline_only, canonical_tree,
)


def test_pending_intent_survives_reopen_and_then_completes(tmp_path):
    package = _package(tmp_path / "source")
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        status = owner.registration_status("op", package.payload())
        assert status == {"schema_version": "source-corpus-operation-status-v1",
                          "operation_id": "op", "state": "unknown", "receipt": None,
                          "admitted": False, "formalized": False}
        pending = owner.reserve_registration("op", package.payload())
        assert pending == {**status, "state": "pending"}
        assert owner.reserve_registration("op", package.payload()) == pending
        assert owner.resolve_operation("op", package.payload()) is None
        assert list(owned.iterdir()) == []
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        assert owner.registration_status("op", package.payload()) == pending
        assert owner.pending_registrations() == [{"operation_id": "op", "payload": package.payload()}]
        receipt = _register(owner, package, "op")
        assert owner.pending_registrations() == []
        assert owner.registration_status("op", package.payload()) == {**pending, "state": "completed", "receipt": receipt}
        assert owner.reserve_registration("op", package.payload())["receipt"] == receipt
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        assert owner.register_export("op", **package.payload(), package_resolver=_no_resolver) == receipt


def test_pending_replay_conflict_capacity_and_detached_payload(tmp_path):
    package = _package(tmp_path / "source")
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned",
                                    limits=catalog.SourceCatalogLimits(max_operations=2)) as owner:
        payload = package.payload()
        owner.reserve_registration("b", payload)
        payload["dataset"]["source_language"] = "fr"
        with pytest.raises(catalog.SourceCorpusCatalogError, match="conflict"):
            owner.reserve_registration("b", payload)
        owner.reserve_registration("a", package.payload("fr"))
        assert [item["operation_id"] for item in owner.pending_registrations(2)] == ["a", "b"]
        page = owner.pending_registrations(2)
        page[1]["payload"]["dataset"]["namespace"] = "changed"
        assert owner.pending_registrations(2)[1]["payload"] == package.payload()
        with pytest.raises(catalog.SourceCorpusCatalogError, match="capacity"):
            owner.reserve_registration("c", package.payload())
        assert owner.registration_status("c", package.payload())["state"] == "unknown"
        assert owner.reserve_registration("b", package.payload())["state"] == "pending"


@pytest.mark.parametrize("limit", [True, 0, -1, 65, 1.0, "1"])
def test_pending_bound_is_checked_before_database_access(tmp_path, monkeypatch, limit):
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        monkeypatch.setattr(owner, "_transaction", lambda: pytest.fail("invalid bound reached database"))
        with pytest.raises(catalog.SourceCorpusCatalogError, match="bound"):
            owner.pending_registrations(limit)


def test_try_access_uses_actual_catalog_lock_and_releases_after_error(tmp_path):
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        entered, release = threading.Event(), threading.Event()

        def work():
            with owner._lock:
                entered.set()
                assert release.wait(5)

        thread = threading.Thread(target=work)
        thread.start()
        try:
            assert entered.wait(5)
            with owner.try_owner_access() as acquired:
                assert acquired is False
        finally:
            release.set()
            thread.join(5)
        assert not thread.is_alive()
        with pytest.raises(RuntimeError, match="interrupted"):
            with owner.try_owner_access() as acquired:
                assert acquired is True
                with owner.try_owner_access() as nested:
                    assert nested is True
                raise RuntimeError("interrupted")
        with owner.try_owner_access() as acquired:
            assert acquired is True
    with pytest.raises(catalog.SourceCorpusCatalogError, match="closed"):
        with owner.try_owner_access():
            pytest.fail("closed catalog acquired")


def test_pending_corrupt_payload_is_rejected(tmp_path):
    package = _package(tmp_path / "source")
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        owner.reserve_registration("op", package.payload())
        with owner._transaction() as cx:
            cx.execute("UPDATE source_corpus.operations SET request_digest=? WHERE operation_id=?", ["0" * 64, "op"])
        with pytest.raises(catalog.SourceCorpusCatalogError, match="corruption"):
            owner.pending_registrations()


def test_pending_prefix_is_literal_and_prevents_foreign_queue_starvation(tmp_path):
    package = _package(tmp_path / "source")
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        for operation in ("a:foreign", "z_scope:own", "zXscope:foreign"):
            owner.reserve_registration(operation, package.payload())
        assert owner.pending_registrations(1)[0]["operation_id"] == "a:foreign"
        assert owner.pending_registrations(1, operation_prefix="z_scope:") == [
            {"operation_id": "z_scope:own", "payload": package.payload()}]
        assert owner.pending_registrations(operation_prefix="missing:") == []
