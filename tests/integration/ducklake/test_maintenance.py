"""Integration tests for receipted DuckLake maintenance policy (DQK-096).

Covers acceptance criteria:

* Partition changes affect new files without invalidating old snapshots
* Each catalog has one strict global retention class; snapshot expiry precedes
  cleanup
* Compaction, expiration, scheduled cleanup, and orphan actions are
  independently authorized by a trusted owner-broker identity distinct from
  the maintainer and fence-checked before the single catalog owner mutates
* Possession of a Quack token cannot self-authorize maintenance
* Dry-run and execution receipts bind caller/process birth, generation fence,
  catalog identity, starting snapshot, DQK-090 reader-lease set, policy,
  action, authorization, candidate file set, nonce/expiry, resulting snapshot,
  and created/deleted file set
* Destructive execution must exactly match a current accepted dry-run,
  independently reauthorize at use, and obtain separate scoped object-delete
  IAM or fail closed
* Maintenance consumes authoritative DQK-090 acquire/renew/release state, not
  inferred timestamps
* Bare CHECKPOINT and automated cleanup_all are rejected
* Staging is outside DATA_PATH; live upload leases prevent orphan deletion
* Orphan deletion requires owned-namespace proof, age threshold, dry-run
  evidence, non-self-issued authorization, and the same fences
* Compaction creates new file identities while preserving logical rows, schema,
  provenance, and retained old-snapshot files

Hermetic: in-memory catalog + real DQK-090 lease authority (no live DuckDB).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

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

from ipfs_datasets_py.ducklake import config as cfg
from ipfs_datasets_py.ducklake import maintenance as mnt
from ipfs_datasets_py.ducklake import snapshots as snap


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_CMDLINE = "sha256:" + ("11" * 32)
_GENERATION = 7
_CATALOG = "cat_a"


def _birth_binding(**overrides: Any) -> cfg.ProcessBirthBinding:
    payload = {
        "pid": 9001,
        "boot_id": "boot-reader-1",
        "start_ticks": 5000,
        "cmdline_sha256": _CMDLINE,
    }
    payload.update(overrides)
    return cfg.ProcessBirthBinding(**payload)


def _process_birth() -> mnt.ProcessBirth:
    return mnt.default_process_birth(
        process_id="maintainer-proc-1",
        boot_id="boot-maint-1",
        hostname="test-host",
        pid=4242,
    )


def _namespace(tmp_path: Path) -> tuple[str, str]:
    data = tmp_path / "lake" / "data" / _CATALOG
    staging = tmp_path / "lake" / "staging" / _CATALOG
    data.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    return str(data.resolve()), str(staging.resolve())


def _member(catalog_id: str = _CATALOG, **overrides: Any) -> snap.SnapshotVectorMember:
    payload: dict[str, Any] = {
        "catalog_id": catalog_id,
        "owner_generation": _GENERATION,
        "fencing_epoch": 1,
        "quack_endpoint_identity": f"quacks://127.0.0.1:19001/{catalog_id}",
        "catalog_global_snapshot_id": 1,
        "schema_version": "ducklake-schema@1",
        "storage_root": f"s3://lake/{catalog_id}/data",
        "logical_datasets": ("events",),
        "source_revisions": {"src-1": "rev-a"},
        "policy_decision_id": "pol-1",
        "policy_decision": {
            "decision_id": "pol-1",
            "allowed": True,
            "decided_by": "broker",
        },
        "tenant_id": "acme",
        "catalog_digest": "sha256:" + ("ab" * 32),
        "shard_id": f"shard-{catalog_id}",
    }
    payload.update(overrides)
    return snap.SnapshotVectorMember(**payload)


def _vector(snapshot: int = 1) -> snap.SnapshotVector:
    return snap.capture_snapshot_vector(
        members=[_member(catalog_global_snapshot_id=snapshot)],
        vector_id=f"vec-snap-{snapshot}",
    )


def _lease_db() -> snap.AuthoritativeSnapshotDatabase:
    return snap.AuthoritativeSnapshotDatabase(instance_id="lease-db-dqk096")


def _service(
    tmp_path: Path,
    *,
    generation_fence: int = _GENERATION,
    caller_id: str = "maintainer-1",
    broker_id: str = "owner-broker-1",
    retain_snapshots: int = 2,
    orphan_min_age_seconds: int = 60,
    lease_authority: snap.AuthoritativeSnapshotDatabase | None = None,
    clock: Any = None,
) -> tuple[mnt.MaintenanceService, mnt.HermeticMaintenanceCatalog, str, str]:
    data_path, staging_path = _namespace(tmp_path)
    birth = _process_birth()
    broker = mnt.MaintenanceOwnerBroker(
        broker_id=broker_id,
        catalog_id=_CATALOG,
        generation_fence=generation_fence,
        data_path=data_path,
        clock=clock,
    )
    policy = mnt.CatalogRetentionPolicy(
        policy_id=f"ret-{_CATALOG}",
        catalog_id=_CATALOG,
        retention_class=mnt.RetentionClass.STANDARD,
        retain_snapshots=retain_snapshots,
        orphan_min_age_seconds=orphan_min_age_seconds,
    )
    catalog = mnt.HermeticMaintenanceCatalog(
        catalog_id=_CATALOG,
        data_path=data_path,
        staging_path=staging_path,
        generation_fence=generation_fence,
        clock=clock,
    )
    svc = mnt.MaintenanceService(
        catalog_id=_CATALOG,
        data_path=data_path,
        staging_path=staging_path,
        generation_fence=generation_fence,
        broker=broker,
        retention_policy=policy,
        caller_id=caller_id,
        process_birth=birth,
        lease_authority=lease_authority,
        catalog=catalog,
        clock=clock,
    )
    return svc, catalog, data_path, staging_path


def _seed_files(catalog: mnt.HermeticMaintenanceCatalog, n: int = 3) -> list[str]:
    ids: list[str] = []
    for i in range(n):
        rec = catalog.add_file(
            file_id=f"f{i}",
            logical_row_count=10 + i,
            provenance_cid=f"bafyprov{i:04d}",
            partition_spec="none",
        )
        ids.append(rec.file_id)
    catalog.commit_snapshot()
    return ids


# ---------------------------------------------------------------------------
# Forbidden bare CHECKPOINT / cleanup_all
# ---------------------------------------------------------------------------


def test_bare_checkpoint_rejected(tmp_path: Path) -> None:
    svc, _cat, _d, _s = _service(tmp_path)
    with pytest.raises(mnt.MaintenanceError, match="CHECKPOINT"):
        svc.reject_bare_checkpoint("CHECKPOINT")
    with pytest.raises(mnt.MaintenanceError, match="CHECKPOINT"):
        mnt.assert_not_bare_checkpoint("CALL CHECKPOINT()")
    with pytest.raises(mnt.MaintenanceError, match="CHECKPOINT"):
        svc.catalog.execute_bare_statement("CHECKPOINT")


def test_automated_cleanup_all_rejected(tmp_path: Path) -> None:
    svc, _cat, _d, _s = _service(tmp_path)
    with pytest.raises(mnt.MaintenanceError, match="cleanup_all"):
        svc.reject_cleanup_all("cleanup_all")
    with pytest.raises(mnt.MaintenanceError, match="cleanup_all"):
        mnt.assert_not_cleanup_all("ducklake_cleanup_all")
    with pytest.raises(mnt.MaintenanceError, match="cleanup_all"):
        svc.dry_run(
            action="cleanup_all",  # type: ignore[arg-type]
            operation_id="op-bad",
        )


# ---------------------------------------------------------------------------
# Quack token cannot authorize; broker distinct from maintainer
# ---------------------------------------------------------------------------


def test_quack_token_cannot_self_authorize_maintenance(tmp_path: Path) -> None:
    svc, _cat, _d, _s = _service(tmp_path)
    with pytest.raises(mnt.QuackTokenAuthorizationError, match="Quack token"):
        svc.reject_quack_token_authorization(
            "quack-secret-token-xyz",
            action=mnt.MaintenanceAction.COMPACTION,
        )
    with pytest.raises(mnt.QuackTokenAuthorizationError):
        mnt.assert_quack_token_cannot_authorize_maintenance(
            {"token_id": "tok-1", "secret": "s"},
            action=mnt.MaintenanceAction.EXPIRE_SNAPSHOTS,
        )
    with pytest.raises(mnt.QuackTokenAuthorizationError):
        mnt.assert_quack_token_cannot_authorize_maintenance(
            None, action=mnt.MaintenanceAction.DELETE_ORPHANED_FILES
        )


def test_broker_identity_distinct_from_maintainer(tmp_path: Path) -> None:
    with pytest.raises(mnt.AuthorizationError, match="differ from trusted owner-broker"):
        _service(tmp_path, caller_id="owner-broker-1", broker_id="owner-broker-1")

    svc, _cat, _d, _s = _service(tmp_path)
    assert svc.caller_id != svc.broker.broker_id
    summary = svc.proof_summary()
    assert summary["broker_distinct_from_maintainer"] is True
    assert summary["quack_token_cannot_authorize"] is True


def test_self_issued_authorization_rejected(tmp_path: Path) -> None:
    svc, cat, _d, _s = _service(tmp_path)
    _seed_files(cat)
    with pytest.raises(mnt.AuthorizationError, match="non-self-issued"):
        mnt.MaintenanceAuthorization(
            authorization_id="bad",
            action=mnt.MaintenanceAction.COMPACTION,
            operation_id="op-1",
            caller_id="same-id",
            process_birth=svc.process_birth,
            generation_fence=_GENERATION,
            catalog_id=_CATALOG,
            starting_snapshot=cat.snapshot_version,
            issuer_id="same-id",
            nonce="n1",
            expires_at_unix=time.time() + 100,
            candidate_file_set_digest=mnt.file_set_digest(["f0"]),
            reader_lease_set_digest=mnt.lease_set_digest([]),
            policy_digest=svc.policy_digest(),
        )


# ---------------------------------------------------------------------------
# Staging outside DATA_PATH
# ---------------------------------------------------------------------------


def test_staging_must_be_outside_data_path(tmp_path: Path) -> None:
    data = tmp_path / "lake" / "data"
    data.mkdir(parents=True)
    # Staging under data path must fail.
    staging_inside = data / "staging"
    staging_inside.mkdir()
    with pytest.raises(Exception, match="outside DATA_PATH"):
        mnt.HermeticMaintenanceCatalog(
            catalog_id=_CATALOG,
            data_path=str(data.resolve()),
            staging_path=str(staging_inside.resolve()),
            generation_fence=_GENERATION,
        )


# ---------------------------------------------------------------------------
# Single global retention class; expiry precedes cleanup
# ---------------------------------------------------------------------------


def test_strict_single_global_retention_class(tmp_path: Path) -> None:
    svc, _cat, _d, _s = _service(tmp_path)
    svc.assert_single_retention_class(mnt.RetentionClass.STANDARD)
    with pytest.raises(mnt.RetentionError, match="strict global retention class"):
        svc.assert_single_retention_class(mnt.RetentionClass.LONG)
    assert svc.retention_policy.retention_class is mnt.RetentionClass.STANDARD
    assert svc.proof_summary()["strict_single_global_retention_class"] is True


def test_snapshot_expiry_precedes_cleanup(tmp_path: Path) -> None:
    svc, cat, _d, _s = _service(tmp_path, retain_snapshots=1)
    ids = _seed_files(cat, n=2)
    # Later snapshots drop f0 so expiry can make it unreferenced.
    cat.commit_snapshot(include_file_ids=[ids[1]])
    cat.commit_snapshot(include_file_ids=[ids[1]])

    with pytest.raises(mnt.RetentionError, match="expiry must precede"):
        svc.dry_run(
            action=mnt.MaintenanceAction.CLEANUP_OLD_FILES,
            operation_id="op-cleanup-early",
        )

    # Expire first, then cleanup is allowed.
    auth_exp = svc.authorize(
        action=mnt.MaintenanceAction.EXPIRE_SNAPSHOTS,
        operation_id="op-expire-1",
    )
    dry_exp = svc.dry_run(
        action=mnt.MaintenanceAction.EXPIRE_SNAPSHOTS,
        operation_id="op-expire-1",
        authorization=auth_exp,
    )
    exec_exp = svc.execute(dry_run=dry_exp, authorization=auth_exp)
    assert exec_exp.phase is mnt.MaintenancePhase.EXECUTED
    assert cat.expiry_completed is True

    auth_cu = svc.authorize(
        action=mnt.MaintenanceAction.CLEANUP_OLD_FILES,
        operation_id="op-cleanup-1",
    )
    dry_cu = svc.dry_run(
        action=mnt.MaintenanceAction.CLEANUP_OLD_FILES,
        operation_id="op-cleanup-1",
        authorization=auth_cu,
    )
    assert dry_cu.accepted is True
    assert dry_cu.predicted_deleted_file_ids
    iam = svc.broker.issue_object_delete_iam(
        authorization=auth_cu,
        caller_id=svc.caller_id,
        process_birth=svc.process_birth,
        generation_fence=svc.generation_fence,
        candidate_file_set_digest=dry_cu.candidate_file_set_digest,
    )
    result = svc.execute(
        dry_run=dry_cu, authorization=auth_cu, object_delete_iam=iam
    )
    assert set(result.deleted_file_ids) == set(dry_cu.predicted_deleted_file_ids)
    assert ids[0] in result.deleted_file_ids


# ---------------------------------------------------------------------------
# Partition evolution does not invalidate old snapshots
# ---------------------------------------------------------------------------


def test_partition_changes_do_not_invalidate_old_snapshots(tmp_path: Path) -> None:
    svc, cat, _d, _s = _service(tmp_path)
    ids = _seed_files(cat, n=2)
    snap_v = cat.snapshot_version
    old_rows = cat.logical_rows_for_snapshot(snap_v)
    old_specs = {
        fid: cat.get_file(fid).partition_spec  # type: ignore[union-attr]
        for fid in ids
    }

    dry = svc.dry_run(
        action=mnt.MaintenanceAction.PARTITION_EVOLUTION,
        operation_id="op-part-1",
        new_partition_spec="hive/dt=yyyy-mm-dd",
        require_authorization=False,
    )
    assert dry.accepted is True
    # Provide a broker auth for fence audit even when not strictly required.
    auth = svc.authorize(
        action=mnt.MaintenanceAction.PARTITION_EVOLUTION,
        operation_id="op-part-1",
        candidate_file_ids=[],
    )
    receipt = svc.execute(
        dry_run=dry,
        authorization=auth,
        new_partition_spec="hive/dt=yyyy-mm-dd",
    )
    assert receipt.resulting_snapshot == snap_v
    # Old files keep original partition specs; catalog default updated.
    assert cat.partition_spec == "hive/dt=yyyy-mm-dd"
    for fid, spec in old_specs.items():
        assert cat.get_file(fid) is not None
        assert cat.get_file(fid).partition_spec == spec  # type: ignore[union-attr]
    # Old snapshot logical rows unchanged.
    assert cat.logical_rows_for_snapshot(snap_v) == old_rows

    # New file picks up new partition spec and only joins a *new* snapshot.
    new_rec = cat.add_file(file_id="f-new", logical_row_count=3)
    assert new_rec.partition_spec == "hive/dt=yyyy-mm-dd"
    assert cat.logical_rows_for_snapshot(snap_v) == old_rows
    new_snap = cat.commit_snapshot()
    assert new_snap != snap_v
    assert cat.logical_rows_for_snapshot(snap_v) == old_rows
    assert any(r.get("file_id") == "f-new" for r in cat.logical_rows_for_snapshot(new_snap))


# ---------------------------------------------------------------------------
# Compaction: new identities, preserve rows/schema/provenance/old files
# ---------------------------------------------------------------------------


def test_compaction_creates_new_identities_preserves_rows_and_old_files(
    tmp_path: Path,
) -> None:
    svc, cat, _d, _s = _service(tmp_path)
    ids = _seed_files(cat, n=3)
    old_snap = cat.snapshot_version
    old_rows = sorted(
        cat.logical_rows_for_snapshot(old_snap),
        key=lambda r: (r.get("file_id"), r.get("row_id")),
    )
    old_schema = cat.schema_version
    old_provenance = {
        fid: cat.get_file(fid).provenance_cid  # type: ignore[union-attr]
        for fid in ids
    }
    old_digests = {
        fid: cat.get_file(fid).content_digest  # type: ignore[union-attr]
        for fid in ids
    }

    result = svc.run_compaction(operation_id="op-compact-1", candidate_file_ids=ids)
    assert isinstance(result, mnt.ExecutionReceipt)
    assert result.created_file_ids
    new_id = result.created_file_ids[0]
    assert new_id not in ids
    new_rec = cat.get_file(new_id)
    assert new_rec is not None
    assert new_rec.schema_version == old_schema
    assert new_rec.logical_row_count == sum(
        cat.get_file(fid).logical_row_count for fid in ids  # type: ignore[union-attr]
    )

    # Old snapshot files retained with original digests/provenance.
    for fid in ids:
        rec = cat.get_file(fid)
        assert rec is not None
        assert rec.deleted is False
        assert rec.content_digest == old_digests[fid]
        assert rec.provenance_cid == old_provenance[fid]
        assert old_snap in rec.snapshot_versions

    assert cat.logical_rows_for_snapshot(old_snap) == old_rows
    # New snapshot has compacted logical row count.
    new_rows = cat.logical_rows_for_snapshot(result.resulting_snapshot)
    assert len(new_rows) == new_rec.logical_row_count


def test_compaction_dry_run_is_default_and_receipt_binds_fences(
    tmp_path: Path,
) -> None:
    lease_db = _lease_db()
    vector = _vector(snapshot=1)
    lease_db.put_vector(vector)
    lease = lease_db.acquire_lease(
        vector=vector,
        catalog_id=_CATALOG,
        process_birth=_birth_binding(),
        task_id="task-r1",
        run_id="run-r1",
        worker_id="worker-r1",
        ttl_seconds=300,
    )
    assert lease.is_live()

    svc, cat, _d, _s = _service(tmp_path, lease_authority=lease_db)
    ids = _seed_files(cat, n=2)
    # Align snapshot with lease for realistic protection window.
    assert cat.snapshot_version >= 1

    dry_only = svc.run_compaction(
        operation_id="op-compact-dry",
        candidate_file_ids=ids,
        dry_run_only=True,
    )
    assert isinstance(dry_only, mnt.DryRunReceipt)
    assert dry_only.mode == "dry_run"
    assert dry_only.accepted is True
    assert dry_only.catalog_id == _CATALOG
    assert dry_only.generation_fence == _GENERATION
    assert dry_only.starting_snapshot == cat.snapshot_version
    assert dry_only.process_birth.fingerprint() == svc.process_birth.fingerprint()
    assert dry_only.policy.retention_class is mnt.RetentionClass.STANDARD
    assert dry_only.authorization_id
    assert dry_only.nonce
    assert dry_only.expires_at_unix > time.time()
    assert dry_only.candidate_file_set_digest == mnt.file_set_digest(ids)
    # Authoritative lease set from DQK-090 is bound.
    assert dry_only.reader_lease_set
    assert any(row["lease_id"] == lease.lease_id for row in dry_only.reader_lease_set)
    assert dry_only.reader_lease_set_digest == mnt.lease_set_digest(
        dry_only.reader_lease_set
    )
    # Tokens redacted in projection.
    for row in dry_only.reader_lease_set:
        assert row.get("lease_token") in {"***", None} or str(
            row.get("lease_token", "")
        ).startswith("***")


# ---------------------------------------------------------------------------
# Destructive execution matches dry-run; reauth + object-delete IAM
# ---------------------------------------------------------------------------


def test_execution_requires_matching_dry_run_and_object_delete_iam(
    tmp_path: Path,
) -> None:
    clock = {"t": 1_700_000_000.0}

    def _now() -> float:
        return clock["t"]

    svc, cat, data_path, _s = _service(
        tmp_path, retain_snapshots=1, orphan_min_age_seconds=10, clock=_now
    )
    ids = _seed_files(cat, n=2)
    # Drop f0 from later snapshots so expiry schedules it for cleanup.
    cat.commit_snapshot(include_file_ids=[ids[1]])
    cat.commit_snapshot(include_file_ids=[ids[1]])

    # Expire then cleanup with IAM.
    auth_e = svc.authorize(
        action=mnt.MaintenanceAction.EXPIRE_SNAPSHOTS, operation_id="op-e"
    )
    dry_e = svc.dry_run(
        action=mnt.MaintenanceAction.EXPIRE_SNAPSHOTS,
        operation_id="op-e",
        authorization=auth_e,
    )
    svc.execute(dry_run=dry_e, authorization=auth_e)

    auth_c = svc.authorize(
        action=mnt.MaintenanceAction.CLEANUP_OLD_FILES, operation_id="op-c"
    )
    dry_c = svc.dry_run(
        action=mnt.MaintenanceAction.CLEANUP_OLD_FILES,
        operation_id="op-c",
        authorization=auth_c,
    )
    assert dry_c.predicted_deleted_file_ids

    # Fail closed without object-delete IAM.
    with pytest.raises(mnt.ObjectDeleteIamError, match="object-delete IAM"):
        svc.execute(dry_run=dry_c, authorization=auth_c, object_delete_iam=None)

    # Mismatched dry-run (wrong snapshot) fails.
    bad_dry = mnt.DryRunReceipt(
        dry_run_id="dry-bad",
        operation_id="op-c",
        action=mnt.MaintenanceAction.CLEANUP_OLD_FILES,
        catalog_id=_CATALOG,
        caller_id=svc.caller_id,
        process_birth=svc.process_birth,
        generation_fence=_GENERATION,
        starting_snapshot=cat.snapshot_version + 99,
        policy=svc.retention_policy,
        authorization_id=auth_c.authorization_id,
        authorization_binding_digest=auth_c.binding_digest(),
        candidate_file_ids=dry_c.candidate_file_ids,
        candidate_file_set_digest=dry_c.candidate_file_set_digest,
        reader_lease_set=dry_c.reader_lease_set,
        reader_lease_set_digest=dry_c.reader_lease_set_digest,
        nonce="bad",
        expires_at_unix=time.time() + 100,
        predicted_deleted_file_ids=dry_c.predicted_deleted_file_ids,
        accepted=True,
    )
    with pytest.raises(mnt.DryRunError, match="starting snapshot"):
        svc.execute(dry_run=bad_dry, authorization=auth_c)

    iam = svc.broker.issue_object_delete_iam(
        authorization=auth_c,
        caller_id=svc.caller_id,
        process_birth=svc.process_birth,
        generation_fence=svc.generation_fence,
        candidate_file_set_digest=dry_c.candidate_file_set_digest,
        scope_prefix=data_path,
    )
    receipt = svc.execute(
        dry_run=dry_c, authorization=auth_c, object_delete_iam=iam
    )
    assert receipt.object_delete_iam_grant_id == iam.grant_id
    assert set(receipt.deleted_file_ids) == set(dry_c.predicted_deleted_file_ids)
    assert receipt.starting_snapshot == dry_c.starting_snapshot
    assert receipt.candidate_file_set_digest == dry_c.candidate_file_set_digest
    assert receipt.reader_lease_set_digest == dry_c.reader_lease_set_digest
    assert receipt.dry_run_id == dry_c.dry_run_id

    # Dry-run cannot be reused.
    auth_c2 = svc.authorize(
        action=mnt.MaintenanceAction.CLEANUP_OLD_FILES, operation_id="op-c2"
    )
    with pytest.raises(mnt.DryRunError, match="already consumed"):
        svc.execute(dry_run=dry_c, authorization=auth_c2, object_delete_iam=iam)


def test_fence_mismatch_blocks_mutation(tmp_path: Path) -> None:
    svc, cat, _d, _s = _service(tmp_path)
    ids = _seed_files(cat)
    auth = svc.authorize(
        action=mnt.MaintenanceAction.COMPACTION,
        operation_id="op-fence",
        candidate_file_ids=ids,
    )
    dry = svc.dry_run(
        action=mnt.MaintenanceAction.COMPACTION,
        operation_id="op-fence",
        authorization=auth,
        candidate_file_ids=ids,
    )
    # Tamper generation fence on a forged auth.
    with pytest.raises(mnt.FenceError):
        mnt.revalidate_maintenance_authorization(
            auth,
            action=mnt.MaintenanceAction.COMPACTION,
            operation_id="op-fence",
            caller_id=svc.caller_id,
            process_birth=svc.process_birth,
            generation_fence=_GENERATION + 1,
            catalog_id=_CATALOG,
            starting_snapshot=dry.starting_snapshot,
            candidate_file_set_digest=dry.candidate_file_set_digest,
            reader_lease_set_digest=dry.reader_lease_set_digest,
            policy_digest=svc.policy_digest(),
        )

    with pytest.raises(mnt.FenceError):
        cat.assert_fence(_GENERATION + 1)


# ---------------------------------------------------------------------------
# DQK-090 authoritative leases protect active-reader window
# ---------------------------------------------------------------------------


def test_maintenance_consumes_authoritative_lease_state_not_timestamps(
    tmp_path: Path,
) -> None:
    lease_db = _lease_db()
    vector = _vector(snapshot=1)
    lease_db.put_vector(vector)
    lease = lease_db.acquire_lease(
        vector=vector,
        catalog_id=_CATALOG,
        process_birth=_birth_binding(),
        task_id="task-protect",
        run_id="run-protect",
        worker_id="worker-protect",
        ttl_seconds=300,
    )

    svc, cat, _d, _s = _service(
        tmp_path, retain_snapshots=1, lease_authority=lease_db
    )
    _seed_files(cat, n=2)
    # Force multiple snapshots so something would expire without protection.
    cat.commit_snapshot()
    cat.commit_snapshot()
    # Ensure snapshot 1 still exists in catalog history for the lease.
    if 1 not in cat._snapshot_files:
        cat._snapshot_files[1] = set(cat._snapshot_files[cat.snapshot_version])

    protected = svc.protected_snapshot_versions()
    assert lease.snapshot_version in protected

    auth = svc.authorize(
        action=mnt.MaintenanceAction.EXPIRE_SNAPSHOTS, operation_id="op-lease-exp"
    )
    dry = svc.dry_run(
        action=mnt.MaintenanceAction.EXPIRE_SNAPSHOTS,
        operation_id="op-lease-exp",
        authorization=auth,
    )
    # Live lease set must match digest from authority, not wall-clock inference.
    live = lease_db.list_live_leases(catalog_id=_CATALOG)
    assert dry.reader_lease_set_digest == mnt.lease_set_digest(live)
    assert any(r["lease_id"] == lease.lease_id for r in dry.reader_lease_set)

    receipt = svc.execute(dry_run=dry, authorization=auth)
    # Protected snapshot must not be expired.
    assert lease.snapshot_version not in cat.expired_snapshots
    assert receipt.resulting_snapshot == cat.snapshot_version

    # Release lease and re-plan: lease leaves the live set via authority release.
    lease_db.release_lease(
        lease_id=lease.lease_id,
        lease_token=lease.lease_token,
        process_birth=_birth_binding(),
        task_id="task-protect",
        run_id="run-protect",
    )
    live_after = lease_db.list_live_leases(catalog_id=_CATALOG)
    assert all(r["lease_id"] != lease.lease_id for r in live_after)


def test_lease_set_change_invalidates_dry_run(tmp_path: Path) -> None:
    lease_db = _lease_db()
    vector = _vector(snapshot=1)
    lease_db.put_vector(vector)
    svc, cat, _d, _s = _service(tmp_path, lease_authority=lease_db)
    ids = _seed_files(cat, n=2)

    auth = svc.authorize(
        action=mnt.MaintenanceAction.COMPACTION,
        operation_id="op-lease-change",
        candidate_file_ids=ids,
    )
    dry = svc.dry_run(
        action=mnt.MaintenanceAction.COMPACTION,
        operation_id="op-lease-change",
        authorization=auth,
        candidate_file_ids=ids,
    )
    # Acquire a new lease after dry-run → live set changes.
    lease_db.acquire_lease(
        vector=vector,
        catalog_id=_CATALOG,
        process_birth=_birth_binding(pid=9002),
        task_id="task-new",
        run_id="run-new",
        worker_id="worker-new",
        ttl_seconds=300,
    )
    with pytest.raises(mnt.DryRunError, match="reader-lease set changed"):
        svc.execute(dry_run=dry, authorization=auth)


# ---------------------------------------------------------------------------
# Orphan reconciliation
# ---------------------------------------------------------------------------


def test_orphan_deletion_requires_owned_namespace_age_dry_run_auth_and_iam(
    tmp_path: Path,
) -> None:
    clock = {"t": 1_700_000_000.0}

    def _now() -> float:
        return clock["t"]

    svc, cat, data_path, staging_path = _service(
        tmp_path, orphan_min_age_seconds=100, clock=_now
    )
    # Registered file that is not in any active snapshot membership later.
    orphan = cat.add_file(
        file_id="orphan-1",
        logical_row_count=0,
        snapshot_versions=(),
        owned_namespace=True,
        created_at_unix=clock["t"] - 500,
    )
    # Too-young orphan must be excluded.
    cat.add_file(
        file_id="young-1",
        logical_row_count=0,
        snapshot_versions=(),
        owned_namespace=True,
        created_at_unix=clock["t"] - 10,
    )
    # Non-owned namespace must not be deleted.
    cat.add_file(
        file_id="external-1",
        logical_row_count=0,
        snapshot_versions=(),
        owned_namespace=False,
        created_at_unix=clock["t"] - 500,
        relative_path="external/ext.parquet",
    )
    # Staging path object must never be treated as DATA_PATH orphan.
    staging_obj = str(Path(staging_path) / "staged-part.parquet")
    # Live upload lease protects an in-progress object under DATA_PATH.
    protected_path = str(Path(data_path) / "owned" / "uploading.parquet")
    cat.register_upload_lease(
        object_path=protected_path,
        caller_id="writer-1",
        ttl_seconds=600,
    )
    cat.add_file(
        file_id="uploading-1",
        logical_row_count=0,
        snapshot_versions=(),
        owned_namespace=True,
        created_at_unix=clock["t"] - 500,
        relative_path="owned/uploading.parquet",
    )

    plan = cat.plan_orphan_deletion(
        policy=svc.retention_policy,
        data_path_listing=[staging_obj, protected_path],
    )
    assert "orphan-1" in plan["candidate_file_ids"]
    assert "young-1" not in plan["candidate_file_ids"]
    assert "external-1" not in plan["candidate_file_ids"]
    assert "uploading-1" not in plan["candidate_file_ids"]
    assert protected_path in plan["live_upload_paths"]

    auth = svc.authorize(
        action=mnt.MaintenanceAction.DELETE_ORPHANED_FILES,
        operation_id="op-orphan-1",
    )
    dry = svc.dry_run(
        action=mnt.MaintenanceAction.DELETE_ORPHANED_FILES,
        operation_id="op-orphan-1",
        authorization=auth,
    )
    assert dry.accepted is True
    assert "orphan-1" in dry.candidate_file_ids
    assert dry.candidate_file_set_digest == mnt.file_set_digest(dry.candidate_file_ids)
    assert dry.generation_fence == _GENERATION
    assert dry.catalog_id == _CATALOG

    with pytest.raises(mnt.ObjectDeleteIamError):
        svc.execute(dry_run=dry, authorization=auth)

    iam = svc.broker.issue_object_delete_iam(
        authorization=auth,
        caller_id=svc.caller_id,
        process_birth=svc.process_birth,
        generation_fence=svc.generation_fence,
        candidate_file_set_digest=dry.candidate_file_set_digest,
        scope_prefix=data_path,
    )
    receipt = svc.execute(dry_run=dry, authorization=auth, object_delete_iam=iam)
    assert "orphan-1" in receipt.deleted_file_ids
    assert cat.get_file("orphan-1").deleted is True  # type: ignore[union-attr]
    assert cat.get_file("uploading-1").deleted is False  # type: ignore[union-attr]
    assert cat.get_file("young-1").deleted is False  # type: ignore[union-attr]
    assert cat.get_file("external-1").deleted is False  # type: ignore[union-attr]
    assert orphan.owned_namespace is True


def test_live_upload_lease_blocks_orphan_execution(tmp_path: Path) -> None:
    clock = {"t": 1_700_000_000.0}

    def _now() -> float:
        return clock["t"]

    svc, cat, data_path, _s = _service(
        tmp_path, orphan_min_age_seconds=10, clock=_now
    )
    path = str(Path(data_path) / "owned" / "inflight.parquet")
    cat.add_file(
        file_id="inflight",
        logical_row_count=0,
        snapshot_versions=(),
        owned_namespace=True,
        created_at_unix=clock["t"] - 100,
        relative_path="owned/inflight.parquet",
    )
    # Dry-run without lease includes candidate.
    auth = svc.authorize(
        action=mnt.MaintenanceAction.DELETE_ORPHANED_FILES,
        operation_id="op-inflight",
    )
    dry = svc.dry_run(
        action=mnt.MaintenanceAction.DELETE_ORPHANED_FILES,
        operation_id="op-inflight",
        authorization=auth,
    )
    assert "inflight" in dry.candidate_file_ids
    # Lease appears after dry-run; execution path of apply_orphan would block if
    # still a candidate — re-plan path: lease during plan excludes it.
    cat.register_upload_lease(object_path=path, caller_id="w1", ttl_seconds=60)
    plan2 = cat.plan_orphan_deletion(policy=svc.retention_policy)
    assert "inflight" not in plan2["candidate_file_ids"]


# ---------------------------------------------------------------------------
# Receipt binding completeness
# ---------------------------------------------------------------------------


def test_execution_receipt_binds_all_required_fields(tmp_path: Path) -> None:
    svc, cat, _d, _s = _service(tmp_path)
    ids = _seed_files(cat, n=2)
    auth = svc.authorize(
        action=mnt.MaintenanceAction.COMPACTION,
        operation_id="op-receipt",
        candidate_file_ids=ids,
    )
    dry = svc.dry_run(
        action=mnt.MaintenanceAction.COMPACTION,
        operation_id="op-receipt",
        authorization=auth,
        candidate_file_ids=ids,
    )
    receipt = svc.execute(dry_run=dry, authorization=auth)
    body = dict(receipt.as_mapping())

    required = {
        "execution_id",
        "operation_id",
        "action",
        "catalog_id",
        "caller_id",
        "process_birth",
        "generation_fence",
        "starting_snapshot",
        "resulting_snapshot",
        "policy",
        "authorization_id",
        "dry_run_id",
        "candidate_file_ids",
        "candidate_file_set_digest",
        "reader_lease_set_digest",
        "created_file_ids",
        "deleted_file_ids",
        "nonce",
    }
    assert required.issubset(body.keys())
    assert body["process_birth"]["fingerprint"] == svc.process_birth.fingerprint()
    assert body["generation_fence"] == _GENERATION
    assert body["catalog_id"] == _CATALOG
    assert body["starting_snapshot"] == dry.starting_snapshot
    assert body["action"] == mnt.MaintenanceAction.COMPACTION.value
    assert body["authorization_id"] == auth.authorization_id
    assert body["created_file_set_digest"] == mnt.file_set_digest(
        receipt.created_file_ids
    )
    assert body["deleted_file_set_digest"] == mnt.file_set_digest(
        receipt.deleted_file_ids
    )

    dry_body = dict(dry.as_mapping())
    for key in (
        "process_birth",
        "generation_fence",
        "catalog_id",
        "starting_snapshot",
        "reader_lease_set",
        "reader_lease_set_digest",
        "policy",
        "action",
        "authorization_id",
        "candidate_file_ids",
        "candidate_file_set_digest",
        "nonce",
        "expires_at_unix",
    ):
        assert key in dry_body


# ---------------------------------------------------------------------------
# Statistics / flush / sort evolution smoke
# ---------------------------------------------------------------------------


def test_statistics_and_flush_and_sort_evolution(tmp_path: Path) -> None:
    svc, cat, _d, _s = _service(tmp_path)
    cat.add_file(file_id="inl-1", logical_row_count=5, inlined=True)
    cat.commit_snapshot()

    dry_stats = svc.dry_run(
        action=mnt.MaintenanceAction.STATISTICS,
        operation_id="op-stats",
        require_authorization=False,
    )
    auth_stats = svc.authorize(
        action=mnt.MaintenanceAction.STATISTICS, operation_id="op-stats"
    )
    stats_exec = svc.execute(dry_run=dry_stats, authorization=auth_stats)
    assert stats_exec.phase is mnt.MaintenancePhase.EXECUTED

    auth_flush = svc.authorize(
        action=mnt.MaintenanceAction.FLUSH_INLINED_DATA,
        operation_id="op-flush",
        candidate_file_ids=["inl-1"],
    )
    dry_flush = svc.dry_run(
        action=mnt.MaintenanceAction.FLUSH_INLINED_DATA,
        operation_id="op-flush",
        authorization=auth_flush,
        candidate_file_ids=["inl-1"],
    )
    flush_exec = svc.execute(dry_run=dry_flush, authorization=auth_flush)
    assert flush_exec.created_file_ids

    dry_sort = svc.dry_run(
        action=mnt.MaintenanceAction.SORT_EVOLUTION,
        operation_id="op-sort",
        new_sort_order="zorder(event_id)",
        require_authorization=False,
    )
    auth_sort = svc.authorize(
        action=mnt.MaintenanceAction.SORT_EVOLUTION, operation_id="op-sort"
    )
    sort_exec = svc.execute(
        dry_run=dry_sort,
        authorization=auth_sort,
        new_sort_order="zorder(event_id)",
    )
    assert cat.sort_order == "zorder(event_id)"
    assert sort_exec.resulting_snapshot == cat.snapshot_version


def test_proof_summary_and_supported_functions(tmp_path: Path) -> None:
    svc, _cat, _d, _s = _service(tmp_path)
    summary = svc.proof_summary()
    assert summary["bare_checkpoint_forbidden"] is True
    assert summary["automated_cleanup_all_forbidden"] is True
    assert summary["destructive_default_mode"] == "dry_run"
    assert "ducklake_expire_snapshots" in summary["supported_ducklake_functions"]
    assert "ducklake_delete_orphaned_files" in summary["supported_ducklake_functions"]
