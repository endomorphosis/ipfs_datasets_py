"""Unit tests for checksummed schema migrations (DQK-003)."""

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
    MigrationRunner,
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
    assert fresh_digest.startswith("schema-digest:sha256:")
    assert schema_digest_for(catalog.migrations) == fresh_digest


def test_dry_run_makes_no_change() -> None:
    catalog = _catalog()
    backend = MemoryMigrationBackend()
    receipts = MigrationRunner(catalog, backend).apply(dry_run=True)
    assert all(r.dry_run and r.status == "dry_run" for r in receipts)
    assert backend.list_applied() == {}
    assert backend.statements == []


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
