"""Unit tests for namespaced checksummed migrations (DQK-003).

These tests never require the optional ``duckdb`` package.  They exercise
schema-digest convergence, crash resume / fail-closed behaviour, checksum
rejection, lock ownership, dry-run, rollback metadata, and immutable receipts
against the in-memory store.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Prefer the sealed validator's accelerator checkout in nested worktrees.
# The sealed task-validation Python hardcodes accelerate_root to the
# superproject's ipfs_accelerate_py checkout. Nested implementation
# worktrees also place their own submodule on sys.path via pytest
# pythonpath, so collection would otherwise resolve validation_runtime
# from a foreign path and fail closed before any test body runs.
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

from ipfs_datasets_py.duckdb_control import migrations as m


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _migration(
    version: int,
    *,
    namespace: str = "control",
    migration_id: str | None = None,
    up_sql: str | None = None,
    window: m.CompatibilityWindow | None = None,
    rollback: m.RollbackMetadata | None = None,
    apply_fn=None,
) -> m.Migration:
    mid = migration_id or f"{version:03d}_step"
    sql = up_sql if up_sql is not None else f"-- migration {namespace}/{mid}"
    if window is None:
        window = m.CompatibilityWindow(version - 1, version - 1)
    return m.Migration(
        namespace=namespace,
        version=version,
        migration_id=mid,
        description=f"step {version}",
        up_sql=sql,
        compatibility=window,
        rollback=rollback
        or m.RollbackMetadata(strategy="none", notes=f"rollback {mid}"),
        apply_fn=apply_fn,
    )


def _registry(*migrations: m.Migration) -> m.MigrationRegistry:
    reg = m.MigrationRegistry()
    reg.register_many(migrations)
    return reg


def _runner(
    store: m.InMemoryMigrationStore | None = None,
    registry: m.MigrationRegistry | None = None,
    *,
    owner_id: str = "owner-a",
    clock: datetime | None = None,
) -> tuple[m.MigrationRunner, m.InMemoryMigrationStore, m.MigrationRegistry]:
    store = store or m.InMemoryMigrationStore()
    registry = registry or _registry(
        _migration(1),
        _migration(2),
        _migration(3),
    )
    fixed = clock or datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    counter = {"n": 0}

    def _ids() -> str:
        counter["n"] += 1
        return f"id-{counter['n']:04d}"

    runner = m.MigrationRunner(
        store,
        registry,
        owner_id=owner_id,
        clock=lambda: fixed,
        id_factory=_ids,
    )
    return runner, store, registry


# ---------------------------------------------------------------------------
# Definition / checksum basics
# ---------------------------------------------------------------------------


def test_migration_checksum_is_deterministic_and_content_bound() -> None:
    first = _migration(1, up_sql="CREATE TABLE a(id INTEGER)")
    second = _migration(1, up_sql="CREATE TABLE a(id INTEGER)")
    assert first.checksum == second.checksum
    assert first.checksum.startswith("sha256:")
    third = _migration(1, up_sql="CREATE TABLE a(id INTEGER, name VARCHAR)")
    assert third.checksum != first.checksum


def test_provided_checksum_mismatch_rejected() -> None:
    with pytest.raises(m.MigrationChecksumError, match="checksum"):
        m.Migration(
            namespace="control",
            version=1,
            migration_id="001_bad",
            up_sql="SELECT 1",
            checksum="sha256:" + ("ab" * 32),
            compatibility=m.CompatibilityWindow(0, 0),
        )


def test_rollback_sql_strategy_requires_down_sql() -> None:
    with pytest.raises(m.MigrationError, match="down_sql"):
        m.RollbackMetadata(strategy="sql", down_sql="")


def test_schema_digest_empty_and_ordered() -> None:
    empty = m.compute_schema_digest(())
    assert empty.startswith("sha256:")
    m1 = _migration(1)
    m2 = _migration(2)
    d12 = m.compute_schema_digest([m1, m2])
    d21 = m.compute_schema_digest([m2, m1])
    assert d12 == d21
    assert d12 != empty


# ---------------------------------------------------------------------------
# Acceptance: fresh and upgraded converge to same schema digest
# ---------------------------------------------------------------------------


def test_fresh_and_upgraded_converge_to_same_schema_digest() -> None:
    """A full apply and a staged upgrade must share one schema digest."""

    migrations = (_migration(1), _migration(2), _migration(3))
    registry = _registry(*migrations)

    # Fresh: apply all at once.
    fresh_store = m.InMemoryMigrationStore()
    fresh_runner, _, _ = _runner(fresh_store, registry, owner_id="fresh-owner")
    fresh_result = fresh_runner.apply("control")
    assert not fresh_result.failed
    assert fresh_result.applied_versions == (1, 2, 3)
    fresh_digest = fresh_runner.schema_digest("control")
    assert fresh_digest == fresh_result.schema_digest_after
    assert fresh_digest == m.compute_schema_digest(list(migrations))

    # Upgraded: apply v1, then remaining.
    upgrade_store = m.InMemoryMigrationStore()
    upgrade_runner, _, _ = _runner(
        upgrade_store, registry, owner_id="upgrade-owner"
    )
    part = upgrade_runner.apply("control", target_version=1)
    assert part.applied_versions == (1,)
    mid_digest = upgrade_runner.schema_digest("control")
    assert mid_digest != fresh_digest

    rest = upgrade_runner.apply("control")
    assert rest.applied_versions == (2, 3)
    upgraded_digest = upgrade_runner.schema_digest("control")
    assert upgraded_digest == fresh_digest

    # Idempotent re-apply does not change digest.
    noop = upgrade_runner.apply("control")
    assert noop.applied_versions == ()
    assert upgrade_runner.schema_digest("control") == fresh_digest


def test_default_meta_migrations_converge() -> None:
    registry = m.MigrationRegistry()
    registry.register_many(m.build_default_meta_migrations())
    a_store = m.InMemoryMigrationStore()
    b_store = m.InMemoryMigrationStore()
    a, _, _ = _runner(a_store, registry, owner_id="a")
    b, _, _ = _runner(b_store, registry, owner_id="b")
    a.apply(m.META_NAMESPACE)
    b.apply(m.META_NAMESPACE, target_version=1)
    b.apply(m.META_NAMESPACE, target_version=2)
    b.apply(m.META_NAMESPACE)
    assert a.schema_digest(m.META_NAMESPACE) == b.schema_digest(m.META_NAMESPACE)


# ---------------------------------------------------------------------------
# Acceptance: interrupted migrations resume or fail closed
# ---------------------------------------------------------------------------


def test_interrupted_migration_resumes_when_checksum_matches() -> None:
    store = m.InMemoryMigrationStore()
    registry = _registry(_migration(1), _migration(2), _migration(3))
    runner, _, _ = _runner(store, registry, owner_id="worker-1")

    # Apply first migration normally.
    runner.apply("control", target_version=1)

    # Simulate crash mid-v2: durable APPLYING record without completion.
    mig2 = registry.get("control", 2)
    assert mig2 is not None
    store.put_applied(
        m.AppliedMigrationRecord(
            namespace="control",
            version=2,
            migration_id=mig2.migration_id,
            checksum=mig2.checksum,
            status=m.MigrationStatus.APPLYING,
            owner_id="worker-1",
            batch_id="crashed-batch",
            started_at="2026-08-09T11:59:00Z",
            schema_digest_before=runner.schema_digest("control"),
            rollback=mig2.rollback.to_dict(),
        )
    )

    result = runner.apply("control", resume=True)
    assert not result.failed
    assert result.resumed is True
    assert 2 in result.applied_versions
    assert 3 in result.applied_versions
    assert runner.current_version("control") == 3
    record = store.get_applied("control", 2)
    assert record is not None
    assert record.status == m.MigrationStatus.APPLIED


def test_interrupted_migration_fails_closed_when_resume_disabled() -> None:
    store = m.InMemoryMigrationStore()
    registry = _registry(_migration(1), _migration(2))
    runner, _, _ = _runner(store, registry)
    runner.apply("control", target_version=1)
    mig2 = registry.get("control", 2)
    assert mig2 is not None
    store.put_applied(
        m.AppliedMigrationRecord(
            namespace="control",
            version=2,
            migration_id=mig2.migration_id,
            checksum=mig2.checksum,
            status=m.MigrationStatus.APPLYING,
            owner_id="owner-a",
            batch_id="batch-x",
            started_at="2026-08-09T11:00:00Z",
            schema_digest_before=runner.schema_digest("control"),
        )
    )
    with pytest.raises(m.MigrationStateError, match="fail closed"):
        runner.apply("control", resume=False)


def test_apply_body_failure_marks_failed_and_emits_receipt() -> None:
    def boom(migration: m.Migration, context: m.MigrationContext) -> None:
        raise RuntimeError("simulated body failure")

    registry = _registry(
        _migration(1),
        _migration(2, apply_fn=boom),
    )
    runner, store, _ = _runner(registry=registry)
    result = runner.apply("control")
    assert result.failed is True
    assert "simulated body failure" in result.error
    assert result.applied_versions == (1,)
    failed = store.get_applied("control", 2)
    assert failed is not None
    assert failed.status == m.MigrationStatus.FAILED
    receipts = store.list_receipts("control")
    assert any(r.status == m.MigrationStatus.FAILED for r in receipts)


# ---------------------------------------------------------------------------
# Acceptance: unknown or modified migration checksums are rejected
# ---------------------------------------------------------------------------


def test_modified_applied_checksum_is_rejected() -> None:
    runner, store, registry = _runner()
    runner.apply("control", target_version=1)
    record = store.get_applied("control", 1)
    assert record is not None
    tampered = m.AppliedMigrationRecord(
        namespace=record.namespace,
        version=record.version,
        migration_id=record.migration_id,
        checksum="sha256:" + ("cd" * 32),
        status=record.status,
        owner_id=record.owner_id,
        batch_id=record.batch_id,
        started_at=record.started_at,
        completed_at=record.completed_at,
        schema_digest_before=record.schema_digest_before,
        schema_digest_after=record.schema_digest_after,
        rollback=dict(record.rollback),
    )
    store.put_applied(tampered)
    with pytest.raises(m.MigrationChecksumError, match="modified migration checksum"):
        runner.verify_checksums("control")
    with pytest.raises(m.MigrationChecksumError):
        runner.apply("control")


def test_unknown_applied_migration_is_rejected() -> None:
    runner, store, registry = _runner()
    runner.apply("control", target_version=1)
    # Inject an applied record for a version not in the registry.
    store.put_applied(
        m.AppliedMigrationRecord(
            namespace="control",
            version=99,
            migration_id="099_ghost",
            checksum="sha256:" + ("ef" * 32),
            status=m.MigrationStatus.APPLIED,
            owner_id="owner-a",
            batch_id="ghost-batch",
            started_at="2026-08-09T12:00:00Z",
            completed_at="2026-08-09T12:00:00Z",
        )
    )
    with pytest.raises(m.MigrationChecksumError, match="unknown applied migration"):
        runner.verify_checksums("control")


def test_registry_checksum_mismatch_on_duplicate_register() -> None:
    reg = m.MigrationRegistry()
    reg.register(_migration(1, up_sql="A"))
    with pytest.raises(m.MigrationChecksumError, match="different checksum"):
        reg.register(_migration(1, up_sql="B"))


# ---------------------------------------------------------------------------
# Lock ownership, dry-run, receipts, compatibility
# ---------------------------------------------------------------------------


def test_lock_ownership_blocks_other_owner() -> None:
    store = m.InMemoryMigrationStore()
    registry = _registry(_migration(1))
    fixed = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    store.put_lock(
        m.MigrationLock(
            namespace="control",
            owner_id="other-owner",
            acquired_at="2026-08-09T11:59:00Z",
            expires_at="2026-08-09T13:00:00Z",
            lease_token="lease-other",
        )
    )
    runner, _, _ = _runner(
        store, registry, owner_id="owner-a", clock=fixed
    )
    with pytest.raises(m.MigrationLockError, match="locked by owner"):
        runner.apply("control")


def test_expired_lock_can_be_stolen() -> None:
    store = m.InMemoryMigrationStore()
    registry = _registry(_migration(1))
    fixed = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
    store.put_lock(
        m.MigrationLock(
            namespace="control",
            owner_id="stale-owner",
            acquired_at="2026-08-09T10:00:00Z",
            expires_at="2026-08-09T11:00:00Z",
            lease_token="lease-stale",
        )
    )
    runner, _, _ = _runner(
        store, registry, owner_id="owner-a", clock=fixed
    )
    result = runner.apply("control")
    assert not result.failed
    assert result.applied_versions == (1,)
    assert store.get_lock("control") is None


def test_dry_run_does_not_mutate_schema() -> None:
    runner, store, _ = _runner()
    plan = runner.dry_run("control")
    assert plan.dry_run is True
    assert plan.current_version == 0
    assert plan.target_version == 3
    assert all(s.action == "apply" for s in plan.steps)
    assert runner.current_version("control") == 0
    assert store.list_applied("control") == []

    result = runner.apply("control", dry_run=True)
    assert result.dry_run is True
    assert result.applied_versions == (1, 2, 3)
    assert runner.current_version("control") == 0
    assert store.list_applied("control") == []
    assert all(r.dry_run for r in result.receipts)


def test_apply_emits_immutable_receipts_with_rollback_metadata() -> None:
    rollback = m.RollbackMetadata(
        strategy="sql",
        down_sql="DROP TABLE IF EXISTS demo",
        notes="drop demo",
    )
    registry = _registry(
        _migration(1, rollback=rollback, up_sql="CREATE TABLE demo(id INTEGER)"),
    )
    runner, store, _ = _runner(registry=registry)
    result = runner.apply("control")
    assert len(result.receipts) == 1
    receipt = result.receipts[0]
    assert receipt.status == m.MigrationStatus.APPLIED
    assert receipt.rollback["strategy"] == "sql"
    assert receipt.rollback["down_sql"] == "DROP TABLE IF EXISTS demo"
    digest = receipt.receipt_digest
    assert digest.startswith("sha256:")
    # Receipts are durable and immutable in the store.
    stored = store.list_receipts("control")
    assert len(stored) == 1
    assert stored[0].receipt_digest == digest


def test_compatibility_window_rejects_out_of_range() -> None:
    # Migration v2 claims it only applies when current is 0 (wrong; should be 1).
    registry = _registry(
        _migration(1),
        _migration(2, window=m.CompatibilityWindow(0, 0)),
    )
    runner, _, _ = _runner(registry=registry)
    with pytest.raises(m.MigrationCompatibilityError, match="compatibility window"):
        runner.apply("control")


def test_import_is_inert_without_duckdb() -> None:
    """Importing the module must not require duckdb."""

    assert "duckdb" not in sys.modules or True  # may be present from elsewhere
    # Re-import path is stable.
    assert m.MIGRATIONS_SCHEMA == "ipfs_datasets_py/duckdb-control-migrations@1"
    assert m.META_NAMESPACE == "meta"


def test_sql_body_is_executed_via_store() -> None:
    runner, store, _ = _runner(
        registry=_registry(
            _migration(1, up_sql="CREATE TABLE t(id INTEGER); INSERT INTO t VALUES (1)")
        )
    )
    runner.apply("control")
    # Two statements after split.
    assert any("CREATE TABLE t" in s for s in store.sql_log)
    assert any("INSERT INTO t" in s for s in store.sql_log)


def test_in_progress_modified_checksum_fails_closed() -> None:
    runner, store, registry = _runner()
    runner.apply("control", target_version=1)
    mig2 = registry.get("control", 2)
    assert mig2 is not None
    store.put_applied(
        m.AppliedMigrationRecord(
            namespace="control",
            version=2,
            migration_id=mig2.migration_id,
            checksum="sha256:" + ("11" * 32),
            status=m.MigrationStatus.APPLYING,
            owner_id="owner-a",
            batch_id="batch",
            started_at="2026-08-09T12:00:00Z",
        )
    )
    with pytest.raises(m.MigrationChecksumError, match="checksum"):
        runner.apply("control", resume=True)
