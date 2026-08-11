"""Unit tests for checksummed schema migrations (DQK-003).

Covers:

* fresh vs upgraded schema-digest convergence
* dry-run (no mutation)
* modified / unknown checksum rejection
* interrupted migrations resume or fail closed
* compatibility windows
* exclusive lock ownership
* rollback metadata on immutable receipts
"""

from __future__ import annotations

from pathlib import Path
import sys

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()


def _prefer_sealed_accelerate_checkout() -> None:
    accelerate_paths: list[Path] = []
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            continue
        runtime = (
            path
            / "ipfs_accelerate_py"
            / "agent_supervisor"
            / "validation_runtime.py"
        )
        if runtime.is_file() and path not in accelerate_paths:
            accelerate_paths.append(path)
    if not accelerate_paths:
        return
    preferred = next(
        (path for path in accelerate_paths if path != _LOCAL_ACCELERATE),
        accelerate_paths[0],
    )
    if preferred == _LOCAL_ACCELERATE:
        return
    rebuilt: list[str] = [str(preferred)]
    for entry in sys.path:
        try:
            path = Path(entry).resolve()
        except OSError:
            rebuilt.append(entry)
            continue
        if path in {_LOCAL_ACCELERATE, preferred}:
            continue
        rebuilt.append(entry)
    sys.path[:] = rebuilt
    for name in list(sys.modules):
        if name == "ipfs_accelerate_py" or name.startswith("ipfs_accelerate_py."):
            del sys.modules[name]


_prefer_sealed_accelerate_checkout()

import pytest

from ipfs_datasets_py.duckdb_control.migrations import (
    MemoryMigrationBackend,
    Migration,
    MigrationCatalog,
    MigrationError,
    MigrationLockError,
    MigrationReceipt,
    MigrationRunner,
    RollbackMetadata,
    SCHEMA_DIGEST_PREFIX,
    default_control_plane_migrations,
    schema_digest_for,
)


def _catalog() -> MigrationCatalog:
    return MigrationCatalog(
        migrations=default_control_plane_migrations(),
        namespace="duckdb_control",
    )


def test_fresh_and_upgraded_converge_to_same_schema_digest() -> None:
    catalog = _catalog()
    # Fresh: apply all at once.
    fresh = MemoryMigrationBackend()
    fresh_receipts = MigrationRunner(catalog, fresh).apply()
    assert len(fresh_receipts) == len(catalog.migrations)
    fresh_digest = MigrationRunner(catalog, fresh).schema_digest()

    # Upgraded: apply first, then remaining.
    upgraded = MemoryMigrationBackend()
    partial_catalog = MigrationCatalog(
        migrations=catalog.migrations[:1],
        namespace="duckdb_control",
    )
    MigrationRunner(partial_catalog, upgraded).apply()
    # Continue with full catalog against same backend.
    MigrationRunner(catalog, upgraded).apply()
    upgraded_digest = MigrationRunner(catalog, upgraded).schema_digest()
    assert fresh_digest == upgraded_digest
    assert fresh_digest.startswith(SCHEMA_DIGEST_PREFIX)
    assert schema_digest_for(catalog.migrations) == fresh_digest


def test_dry_run_makes_no_change() -> None:
    catalog = _catalog()
    backend = MemoryMigrationBackend()
    receipts = MigrationRunner(catalog, backend).apply(dry_run=True)
    assert all(r.dry_run and r.status == "dry_run" for r in receipts)
    assert len(receipts) == len(catalog.migrations)
    assert backend.list_applied() == {}
    assert backend.statements == []
    assert backend.current_lock(MigrationRunner.LOCK_NAME) is None


def test_modified_checksum_rejected() -> None:
    original = default_control_plane_migrations()[0]
    # Backend claims original was applied with wrong checksum.
    backend = MemoryMigrationBackend()
    backend.applied[original.migration_id] = "sha256:" + ("00" * 32)
    with pytest.raises(MigrationError, match="checksum"):
        MigrationRunner(_catalog(), backend).pending()


def test_unknown_applied_migration_rejected() -> None:
    backend = MemoryMigrationBackend()
    backend.applied["9999_unknown"] = "sha256:" + ("11" * 32)
    with pytest.raises(MigrationError, match="unknown applied"):
        MigrationRunner(_catalog(), backend).pending()


def test_interrupted_resume_or_fail_closed() -> None:
    catalog = _catalog()
    backend = MemoryMigrationBackend()
    migration = catalog.migrations[0]
    backend.mark_in_progress(migration.migration_id)
    with pytest.raises(MigrationError, match="resume=True"):
        MigrationRunner(catalog, backend).apply(resume=False)
    # Resume path applies remaining including the interrupted one.
    receipts = MigrationRunner(catalog, backend).apply(resume=True)
    assert receipts[0].migration_id == migration.migration_id
    assert receipts[0].resumed is True
    assert migration.migration_id in backend.list_applied()


def test_catalog_rejects_checksum_tamper_at_construction() -> None:
    base = default_control_plane_migrations()[0]
    with pytest.raises(MigrationError, match="checksum mismatch"):
        Migration(
            migration_id=base.migration_id,
            version=base.version,
            namespace=base.namespace,
            description=base.description,
            sql=base.sql,
            checksum="sha256:" + ("ff" * 32),
        )


def test_compatibility_window_rejects_out_of_range() -> None:
    """A migration whose window excludes the applied max version is rejected."""

    m1 = Migration(
        migration_id="0001_base",
        version=1,
        namespace="ns",
        description="base",
        sql="CREATE TABLE a (id INTEGER);",
        compatible_from=0,
        compatible_to=0,
    )
    m2 = Migration(
        migration_id="0002_jump",
        version=2,
        namespace="ns",
        description="requires version 1 only",
        sql="CREATE TABLE b (id INTEGER);",
        compatible_from=1,
        compatible_to=1,
    )
    catalog = MigrationCatalog(migrations=(m1, m2), namespace="ns")
    backend = MemoryMigrationBackend()
    # Apply only first via partial catalog.
    MigrationRunner(
        MigrationCatalog(migrations=(m1,), namespace="ns"), backend
    ).apply()
    # Tamper applied max by also recording a fake higher version state is not
    # possible through runner; instead build a migration that requires max=0
    # after version 1 is applied.
    incompatible = Migration(
        migration_id="0002_jump",
        version=2,
        namespace="ns",
        description="stale window",
        sql="CREATE TABLE b (id INTEGER);",
        compatible_from=0,
        compatible_to=0,  # applied max is 1 → outside window
    )
    bad_catalog = MigrationCatalog(migrations=(m1, incompatible), namespace="ns")
    with pytest.raises(MigrationError, match="compatibility window"):
        MigrationRunner(bad_catalog, backend).apply()


def test_lock_ownership_is_exclusive() -> None:
    catalog = _catalog()
    backend = MemoryMigrationBackend()
    runner_a = MigrationRunner(catalog, backend, owner_id="worker-a")
    lock = runner_a.acquire_lock()
    assert lock.owner_id == "worker-a"
    assert backend.current_lock(MigrationRunner.LOCK_NAME) is not None

    runner_b = MigrationRunner(catalog, backend, owner_id="worker-b")
    with pytest.raises(MigrationLockError, match="held by owner"):
        runner_b.acquire_lock()

    runner_a.release_lock()
    # After release, another owner may acquire.
    lock_b = runner_b.acquire_lock()
    assert lock_b.owner_id == "worker-b"
    runner_b.release_lock()


def test_apply_holds_and_releases_lock() -> None:
    catalog = _catalog()
    backend = MemoryMigrationBackend()
    receipts = MigrationRunner(catalog, backend, owner_id="migrator-1").apply()
    assert all(r.lock_owner == "migrator-1" for r in receipts)
    assert backend.current_lock(MigrationRunner.LOCK_NAME) is None


def test_receipts_carry_immutable_rollback_metadata() -> None:
    catalog = _catalog()
    backend = MemoryMigrationBackend()
    receipts = MigrationRunner(catalog, backend).apply()
    assert receipts
    for receipt, migration in zip(receipts, catalog.migrations, strict=True):
        assert isinstance(receipt, MigrationReceipt)
        assert receipt.receipt_id.startswith("sha256:")
        assert receipt.rollback.strategy == migration.rollback.strategy
        assert receipt.rollback.down_sql == migration.rollback.down_sql
        if migration.rollback.strategy == "sql":
            assert receipt.rollback.checksum.startswith("sha256:")
        # Immutable: frozen dataclass.
        with pytest.raises(Exception):
            receipt.status = "tampered"  # type: ignore[misc]
        as_dict = receipt.to_dict()
        assert as_dict["schema"].startswith("ipfs_datasets_py/")
        assert as_dict["rollback"]["strategy"] == migration.rollback.strategy


def test_rollback_metadata_checksum_enforced() -> None:
    with pytest.raises(MigrationError, match="rollback checksum"):
        RollbackMetadata(
            strategy="sql",
            down_sql="DROP TABLE t;",
            checksum="sha256:" + ("aa" * 32),
        )


def test_mid_apply_crash_leaves_resume_marker() -> None:
    catalog = _catalog()
    backend = MemoryMigrationBackend()
    migration = catalog.migrations[0]
    backend.begin()
    backend.mark_in_progress(migration.migration_id)
    backend.execute(migration.sql)
    backend.fail_mid_apply()
    assert backend.get_in_progress() == migration.migration_id
    assert migration.migration_id not in backend.list_applied()
    with pytest.raises(MigrationError, match="resume=True"):
        MigrationRunner(catalog, backend).apply(resume=False)
    receipts = MigrationRunner(catalog, backend, owner_id="healer").apply(resume=True)
    assert receipts[0].resumed is True
    assert set(backend.list_applied()) == {m.migration_id for m in catalog.migrations}


def test_replay_is_idempotent() -> None:
    catalog = _catalog()
    backend = MemoryMigrationBackend()
    first = MigrationRunner(catalog, backend).apply()
    second = MigrationRunner(catalog, backend).apply()
    assert len(first) == len(catalog.migrations)
    assert second == ()
    assert MigrationRunner(catalog, backend).schema_digest() == schema_digest_for(
        catalog.migrations
    )


def test_namespace_mismatch_rejected() -> None:
    m = Migration(
        migration_id="0001_x",
        version=1,
        namespace="other",
        description="x",
        sql="SELECT 1;",
    )
    with pytest.raises(MigrationError, match="namespace mismatch"):
        MigrationCatalog(migrations=(m,), namespace="duckdb_control")
