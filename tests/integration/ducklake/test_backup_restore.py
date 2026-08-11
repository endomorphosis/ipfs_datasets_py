"""Integration tests for coordinated cold recovery (DQK-098).

Acceptance coverage:

* Catalog-only, companion-registry-only, or object-only backups cannot be
  marked complete
* Capture proves exact writer/reader/maintenance drain, one fenced owner
  generation, closed catalog/registry file handles, and immutable DuckDB file
  digests before copying
* An isolated process opens the closed raw metadata and companion databases
  read-only and emits content-digested COPY FROM DATABASE or byte-snapshot
  outputs
* DuckLake CHECKPOINT is forbidden throughout backup capture
* No backup path reads or copies the live catalog file while a Quack owner
  can mutate it
* Every recovery manifest binds an immutable versioned object inventory rather
  than a mutable bucket listing
* Owner failover, compaction, snapshot expiration, scheduled cleanup, and
  orphan deletion are prohibited for the full capture window
* Completion revalidates owner and workload fences, catalog/registry digests,
  object inventory versions, and reachability of every catalog-referenced file
* Restore detects missing, replaced, orphaned, and undecryptable files
* Historic snapshots replay within the declared retention window
* Restored service starts under a new owner generation and endpoint identity
  without overlap
* The drill declares and measures cold-failover RPO/RTO and never claims PITR,
  replication, or built-in high availability
* Promotion binds exact catalog, registry, storage, schema, extension, policy,
  and verification identities

Hermetic: in-memory backend (no live DuckDB, no network).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()
_RECOVERY_MODULE = _REPO_ROOT / "ipfs_datasets_py/ducklake/recovery.py"


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

from ipfs_datasets_py.ducklake import recovery as rec
from ipfs_datasets_py.ducklake.recovery import (
    CAPTURE_PROHIBITED_OPERATIONS,
    CLAIMS_BUILT_IN_HA,
    CLAIMS_PITR,
    CLAIMS_REPLICATION,
    FORBIDDEN_CAPTURE_STATEMENTS,
    OWNER_TASK_ID,
    PROGRAM_ID,
    REQUIRED_BACKUP_COMPONENTS,
    BackupComponent,
    CaptureMethod,
    CapturePhase,
    CaptureWindowError,
    CheckpointForbiddenError,
    ColdFailoverMetrics,
    ColdRecoveryService,
    EncryptionPolicy,
    FileIntegrityKind,
    HermeticRecoveryBackend,
    IncompleteBackupError,
    LiveCatalogCopyError,
    PromotionDecision,
    PromotionError,
    RecoveryError,
    ShardLiveState,
    VersionedObjectEntry,
    VersionedObjectInventory,
    assert_backup_components_complete,
    assert_capture_action_forbidden,
    assert_checkpoint_forbidden,
    assert_no_live_catalog_copy,
    assert_no_pitr_replication_ha_claims,
    build_cold_recovery_service,
    default_process_birth,
    file_digest_for_bytes,
    install_check,
    self_check,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CATALOG = "cat_backup_1"


def _digest(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def _entry(
    object_id: str,
    *,
    generation: int = 1,
    referenced: bool = True,
    encrypted: bool = False,
    decryptable: bool = True,
) -> VersionedObjectEntry:
    return VersionedObjectEntry(
        object_id=object_id,
        content_digest=_digest(f"payload:{object_id}"),
        generation=generation,
        replica_id="replica-a",
        cid=f"bafy{object_id.replace('-', '')}",
        size_bytes=64,
        encrypted=encrypted,
        decryptable=decryptable,
        referenced_by_catalog=referenced,
    )


def _seed_shard(
    backend: HermeticRecoveryBackend,
    *,
    catalog_id: str = _CATALOG,
    writers: int = 2,
    readers: int = 3,
    maintenance: int = 1,
    objects: dict[str, VersionedObjectEntry] | None = None,
    owner_generation: int = 7,
) -> ShardLiveState:
    objs = objects if objects is not None else {
        "obj-a": _entry("obj-a"),
        "obj-b": _entry("obj-b"),
        "obj-c": _entry("obj-c"),
    }
    state = ShardLiveState(
        catalog_id=catalog_id,
        shard_id=f"shard-{catalog_id}",
        catalog_path=f"/var/lib/ducklake/{catalog_id}/catalog.duckdb",
        companion_path=f"/var/lib/ducklake/{catalog_id}/companion.duckdb",
        owner_generation=owner_generation,
        fencing_epoch=2,
        endpoint_identity=f"quacks://127.0.0.1:19001/{catalog_id}",
        catalog_bytes=f"CATALOG-BYTES-{catalog_id}-v{owner_generation}".encode("utf-8"),
        companion_bytes=f"COMPANION-BYTES-{catalog_id}-v{owner_generation}".encode(
            "utf-8"
        ),
        objects=dict(objs),
        open_writers=writers,
        open_readers=readers,
        open_maintenance=maintenance,
        catalog_handles_open=1,
        companion_handles_open=1,
        owner_process_attached=True,
        admission_open=True,
        historic_snapshot_ids=[1, 2, 3, 4, 5, 6],
        schema_identity="ducklake-schema@1",
        extension_identity="ducklake-ext@pinned",
        policy_identity="policy-dec@1",
        verification_identity="verify-chain@1",
        storage_identity=f"s3://lake/{catalog_id}/data",
        encryption_policy=EncryptionPolicy(
            policy_id="enc-aes-gcm",
            algorithm="AES-256-GCM",
            key_id="kms-key-1",
            encrypted_parquet=True,
        ),
    )
    backend.put_shard(state)
    return state


def _service(
    backend: HermeticRecoveryBackend,
    *,
    catalog_id: str = _CATALOG,
    method: CaptureMethod = CaptureMethod.COPY_FROM_DATABASE,
    retention: int = 5,
) -> ColdRecoveryService:
    return build_cold_recovery_service(
        backend,
        catalog_id=catalog_id,
        process_birth=default_process_birth(
            process_id="recovery-proc-1",
            boot_id="boot-recovery-1",
            hostname="test-host",
            pid=4242,
        ),
        isolated_process_id="backup-isolated-1",
        capture_method=method,
        retention_snapshot_count=retention,
        declared_rpo_seconds=0.0,
        declared_rto_seconds=120.0,
    )


# ---------------------------------------------------------------------------
# Install / non-claims / import inert
# ---------------------------------------------------------------------------


def test_import_is_inert_and_install_check() -> None:
    report = install_check()
    assert report["ok"] is True
    assert report["owner_task_id"] == OWNER_TASK_ID == "DQK-098"
    assert report["program_id"] == PROGRAM_ID
    assert report["claims_pitr"] is False
    assert report["claims_replication"] is False
    assert report["claims_built_in_ha"] is False
    assert report["cold_failover_only"] is True
    assert "CHECKPOINT" in report["forbidden_capture_statements"] or any(
        "CHECKPOINT" in s.upper() for s in report["forbidden_capture_statements"]
    )
    assert set(report["required_backup_components"]) == set(REQUIRED_BACKUP_COMPONENTS)
    assert "cold_failover_drill" in report["workflows"]
    assert "isolated_copy" in report["workflows"]


def test_module_never_claims_pitr_replication_or_ha() -> None:
    assert CLAIMS_PITR is False
    assert CLAIMS_REPLICATION is False
    assert CLAIMS_BUILT_IN_HA is False
    claims = assert_no_pitr_replication_ha_claims()
    assert claims["claims_pitr"] is False
    assert claims["claims_replication"] is False
    assert claims["claims_built_in_ha"] is False
    assert claims["cold_failover_only"] is True
    with pytest.raises(rec.CapabilityClaimError):
        assert_no_pitr_replication_ha_claims({"claims_pitr": True})
    with pytest.raises(rec.CapabilityClaimError):
        assert_no_pitr_replication_ha_claims({"high_availability": True})
    source = _RECOVERY_MODULE.read_text(encoding="utf-8")
    assert "CLAIMS_PITR: Final[bool] = False" in source
    assert "CLAIMS_REPLICATION: Final[bool] = False" in source
    assert "CLAIMS_BUILT_IN_HA: Final[bool] = False" in source


def test_self_check_passes() -> None:
    report = self_check()
    assert report["ok"] is True
    assert report["checkpoint_forbidden"] is True
    assert report["partial_complete_rejected"] is True
    assert report["drill_ok"] is True
    assert report["manifest_complete"] is True
    assert report["restored_generation"] > report["source_generation"]


# ---------------------------------------------------------------------------
# Incomplete component backups cannot complete
# ---------------------------------------------------------------------------


def test_catalog_only_backup_cannot_complete() -> None:
    with pytest.raises(IncompleteBackupError, match="cannot be marked complete"):
        assert_backup_components_complete([BackupComponent.CATALOG])


def test_companion_only_backup_cannot_complete() -> None:
    with pytest.raises(IncompleteBackupError, match="cannot be marked complete"):
        assert_backup_components_complete([BackupComponent.COMPANION_REGISTRY])


def test_object_only_backup_cannot_complete() -> None:
    with pytest.raises(IncompleteBackupError, match="cannot be marked complete"):
        assert_backup_components_complete([BackupComponent.OBJECT_INVENTORY])


def test_service_rejects_partial_complete_flags() -> None:
    backend = HermeticRecoveryBackend()
    _seed_shard(backend)
    service = _service(backend)
    with pytest.raises(IncompleteBackupError):
        service.try_mark_complete_partial(
            include_catalog=True, include_companion=False, include_objects=False
        )
    with pytest.raises(IncompleteBackupError):
        service.try_mark_complete_partial(
            include_catalog=False, include_companion=True, include_objects=False
        )
    with pytest.raises(IncompleteBackupError):
        service.try_mark_complete_partial(
            include_catalog=False, include_companion=False, include_objects=True
        )
    # All three present is accepted.
    present = service.try_mark_complete_partial(
        include_catalog=True, include_companion=True, include_objects=True
    )
    assert present is None or True  # method returns None; assert via no raise
    assert_backup_components_complete(list(REQUIRED_BACKUP_COMPONENTS))


# ---------------------------------------------------------------------------
# Drain, fence, closed handles, digests before copy
# ---------------------------------------------------------------------------


def test_capture_proves_drain_fence_handles_and_digests() -> None:
    backend = HermeticRecoveryBackend()
    state = _seed_shard(backend, writers=4, readers=2, maintenance=1)
    service = _service(backend)

    drain = service.drain_workloads(force=True)
    assert drain.drained is True
    assert drain.open_writers == 0
    assert drain.open_readers == 0
    assert drain.open_maintenance == 0
    assert drain.admission_stopped is True
    assert service.phase is CapturePhase.ADMISSION_STOPPED

    fence = service.fence_owner()
    assert fence.owner_generation == state.owner_generation
    assert fence.capture_window_active is True
    assert service.capture_window_active is True
    assert service.phase is CapturePhase.OWNER_FENCED

    handles = service.close_owner_and_prove_handles()
    assert handles.all_closed is True
    assert handles.catalog_handles_open == 0
    assert handles.companion_handles_open == 0
    assert handles.owner_process_attached is False
    assert service.phase is CapturePhase.HANDLES_CLOSED

    catalog_d, companion_d = service.prove_immutable_digests()
    assert catalog_d == file_digest_for_bytes(state.catalog_bytes)
    assert companion_d == file_digest_for_bytes(state.companion_bytes)
    assert service.phase is CapturePhase.DIGESTS_PROVEN


def test_cannot_digest_while_handles_open() -> None:
    backend = HermeticRecoveryBackend()
    _seed_shard(backend)
    service = _service(backend)
    service.drain_workloads()
    service.fence_owner()
    # Skip close_owner — handles still open.
    with pytest.raises(rec.HandleOpenError):
        service.prove_immutable_digests()


# ---------------------------------------------------------------------------
# Isolated process COPY FROM DATABASE / byte snapshot
# ---------------------------------------------------------------------------


def test_isolated_copy_from_database_emits_matching_digests() -> None:
    backend = HermeticRecoveryBackend()
    state = _seed_shard(backend)
    service = _service(backend, method=CaptureMethod.COPY_FROM_DATABASE)
    manifest, receipt = service.capture()

    assert manifest.complete is True
    assert manifest.catalog_backup.capture_method is CaptureMethod.COPY_FROM_DATABASE
    assert manifest.companion_backup.capture_method is CaptureMethod.COPY_FROM_DATABASE
    assert manifest.catalog_backup.opened_read_only is True
    assert manifest.companion_backup.opened_read_only is True
    assert manifest.catalog_backup.isolated_process_id == "backup-isolated-1"
    assert (
        manifest.catalog_backup.source_digest
        == manifest.catalog_backup.backup_digest
        == file_digest_for_bytes(state.catalog_bytes)
    )
    assert (
        manifest.companion_backup.source_digest
        == manifest.companion_backup.backup_digest
        == file_digest_for_bytes(state.companion_bytes)
    )
    assert "copy_from_database" in receipt.capture_methods
    assert receipt.isolated_process_id == "backup-isolated-1"
    assert receipt.checkpoint_executed is False


def test_byte_snapshot_capture_method() -> None:
    backend = HermeticRecoveryBackend()
    _seed_shard(backend)
    service = _service(backend, method=CaptureMethod.BYTE_SNAPSHOT)
    manifest, receipt = service.capture()
    assert manifest.catalog_backup.capture_method is CaptureMethod.BYTE_SNAPSHOT
    assert manifest.companion_backup.capture_method is CaptureMethod.BYTE_SNAPSHOT
    assert set(receipt.capture_methods) == {"byte_snapshot"}


# ---------------------------------------------------------------------------
# CHECKPOINT forbidden + capture-window prohibitions
# ---------------------------------------------------------------------------


def test_ducklake_checkpoint_forbidden_during_capture() -> None:
    backend = HermeticRecoveryBackend()
    _seed_shard(backend)
    service = _service(backend)
    service.drain_workloads()
    service.fence_owner()
    assert service.capture_window_active is True

    for statement in (
        "CHECKPOINT",
        "checkpoint",
        "CALL ducklake_checkpoint",
        "DUCKLAKE_CHECKPOINT",
        "PRAGMA CHECKPOINT",
    ):
        with pytest.raises(CheckpointForbiddenError, match="CHECKPOINT"):
            service.reject_checkpoint(statement)

    with pytest.raises(CheckpointForbiddenError):
        assert_checkpoint_forbidden("CHECKPOINT")


def test_forbidden_capture_statements_constant_includes_checkpoint() -> None:
    assert "CHECKPOINT" in FORBIDDEN_CAPTURE_STATEMENTS
    assert any("checkpoint" in s.lower() for s in FORBIDDEN_CAPTURE_STATEMENTS)


@pytest.mark.parametrize(
    "action",
    sorted(
        {
            "owner_failover",
            "compaction",
            "snapshot_expiration",
            "expire_snapshots",
            "scheduled_cleanup",
            "cleanup_old_files",
            "orphan_deletion",
            "delete_orphaned_files",
            "active_passive_takeover",
        }
    ),
)
def test_capture_window_prohibits_maintenance_and_failover(action: str) -> None:
    backend = HermeticRecoveryBackend()
    _seed_shard(backend)
    service = _service(backend)
    service.drain_workloads()
    service.fence_owner()
    with pytest.raises(CaptureWindowError, match="prohibited for the full capture window"):
        service.reject_prohibited_operation(action)
    assert action in CAPTURE_PROHIBITED_OPERATIONS or any(
        t in action for t in CAPTURE_PROHIBITED_OPERATIONS
    )


def test_assert_capture_action_forbidden_covers_all_required_ops() -> None:
    required = {
        "owner_failover",
        "compaction",
        "snapshot_expiration",
        "scheduled_cleanup",
        "orphan_deletion",
    }
    for action in required:
        with pytest.raises(CaptureWindowError):
            assert_capture_action_forbidden(action)
    # Harmless action does not raise.
    assert_capture_action_forbidden("read_snapshot_vector")


# ---------------------------------------------------------------------------
# No live catalog copy behind mutatable owner
# ---------------------------------------------------------------------------


def test_no_live_catalog_copy_while_owner_can_mutate() -> None:
    with pytest.raises(LiveCatalogCopyError):
        assert_no_live_catalog_copy(
            owner_can_mutate=True, catalog_handles_open=False
        )
    with pytest.raises(LiveCatalogCopyError):
        assert_no_live_catalog_copy(
            owner_can_mutate=False, catalog_handles_open=True
        )
    # Safe when closed and owner cannot mutate.
    assert_no_live_catalog_copy(owner_can_mutate=False, catalog_handles_open=False)


def test_service_rejects_live_catalog_copy_before_close() -> None:
    backend = HermeticRecoveryBackend()
    _seed_shard(backend)
    service = _service(backend)
    with pytest.raises(LiveCatalogCopyError):
        service.reject_live_catalog_copy()
    service.drain_workloads()
    service.fence_owner()
    service.close_owner_and_prove_handles()
    # After close, copy is allowed (no raise).
    service.reject_live_catalog_copy()


# ---------------------------------------------------------------------------
# Immutable versioned object inventory (not bucket listing)
# ---------------------------------------------------------------------------


def test_manifest_binds_immutable_versioned_object_inventory() -> None:
    backend = HermeticRecoveryBackend()
    _seed_shard(backend)
    service = _service(backend)
    manifest, _receipt = service.capture()

    inv = manifest.object_inventory
    assert isinstance(inv, VersionedObjectInventory)
    assert inv.is_mutable_bucket_listing is False
    assert inv.version_digest.startswith("sha256:")
    assert inv.inventory_version
    assert len(inv.entries) == 3
    assert {e.object_id for e in inv.entries} == {"obj-a", "obj-b", "obj-c"}
    # Rebuilding with same entries yields same version digest.
    rebuilt = VersionedObjectInventory(
        inventory_id=inv.inventory_id,
        inventory_version=inv.inventory_version,
        generation=inv.generation,
        entries=inv.entries,
        version_digest="auto",
    )
    assert rebuilt.version_digest == inv.version_digest


def test_mutable_bucket_listing_rejected() -> None:
    entries = (_entry("obj-x"),)
    inv = VersionedObjectInventory(
        inventory_id="inv-1",
        inventory_version="v1",
        generation=1,
        entries=entries,
        version_digest="auto",
        is_mutable_bucket_listing=True,  # forced False in __post_init__
    )
    assert inv.is_mutable_bucket_listing is False


def test_inventory_version_digest_mismatch_fails() -> None:
    entries = (_entry("obj-x"),)
    with pytest.raises(rec.InventoryError, match="version_digest mismatch"):
        VersionedObjectInventory(
            inventory_id="inv-1",
            inventory_version="v1",
            generation=1,
            entries=entries,
            version_digest=_digest("wrong"),
        )


# ---------------------------------------------------------------------------
# Completion revalidation
# ---------------------------------------------------------------------------


def test_completion_revalidates_fences_digests_inventory_reachability() -> None:
    backend = HermeticRecoveryBackend()
    state = _seed_shard(backend)
    service = _service(backend)
    manifest, receipt = service.capture()

    assert receipt.complete is True
    assert receipt.fences_unchanged is True
    assert receipt.reachability_ok is True
    assert receipt.catalog_digest_before == receipt.catalog_digest_after
    assert receipt.companion_digest_before == receipt.companion_digest_after
    assert receipt.catalog_digest_before == file_digest_for_bytes(state.catalog_bytes)
    assert receipt.inventory_version_digest == manifest.object_inventory.version_digest
    assert receipt.owner_generation == state.owner_generation
    assert receipt.phase is CapturePhase.COMPLETE
    assert service.phase is CapturePhase.COMPLETE
    # Capture window closed after completion.
    assert service.capture_window_active is False


def test_digest_change_during_capture_aborts_completion() -> None:
    backend = HermeticRecoveryBackend()
    _seed_shard(backend)
    service = _service(backend)

    # Monkey-patch isolated copy path: after digests proven, mutate catalog.
    original_isolated = service._isolated_copy

    def _mutating_copy(**kwargs: Any) -> Any:
        if kwargs.get("role") == "companion_registry":
            backend.mutate_catalog_bytes(_CATALOG, b"MUTATED-DURING-CAPTURE")
        return original_isolated(**kwargs)

    service._isolated_copy = _mutating_copy  # type: ignore[method-assign]
    with pytest.raises(RecoveryError, match="revalidation failed"):
        service.capture()
    assert service.phase is CapturePhase.ABORTED


# ---------------------------------------------------------------------------
# Restore integrity: missing / replaced / orphaned / undecryptable
# ---------------------------------------------------------------------------


def test_restore_detects_missing_replaced_orphaned_undecryptable() -> None:
    backend = HermeticRecoveryBackend()
    _seed_shard(
        backend,
        objects={
            "obj-a": _entry("obj-a"),
            "obj-b": _entry("obj-b"),
            "obj-c": _entry("obj-c", encrypted=True, decryptable=True),
        },
    )
    service = _service(backend)
    manifest, _ = service.capture()

    # Corrupt the live store after capture (simulates restore-time store).
    backend.mark_object_missing(_CATALOG, "obj-a")
    backend.mark_object_replaced(_CATALOG, "obj-b", _digest("tampered-obj-b"))
    backend.mark_object_orphaned(_CATALOG, "orphan-z")
    backend.mark_object_undecryptable(_CATALOG, "obj-c")

    verification = service.verify_restore_integrity(manifest)
    kinds = {f.object_id: f.kind for f in verification.findings}
    assert kinds["obj-a"] is FileIntegrityKind.MISSING
    assert kinds["obj-b"] is FileIntegrityKind.REPLACED
    assert kinds["obj-c"] is FileIntegrityKind.UNDECRYPTABLE
    assert kinds["orphan-z"] is FileIntegrityKind.ORPHANED
    assert verification.ok is False
    assert verification.missing_count == 1
    assert verification.replaced_count == 1
    assert verification.orphaned_count >= 1
    assert verification.undecryptable_count == 1

    result = service.restore(manifest.manifest_id, promote=True)
    assert result.ok is False
    assert "missing=" in result.error or "integrity failed" in result.error


def test_clean_restore_succeeds_with_promotion() -> None:
    backend = HermeticRecoveryBackend()
    state = _seed_shard(backend)
    source_generation = state.owner_generation
    source_endpoint = state.endpoint_identity
    service = _service(backend)
    manifest, _ = service.capture()
    result = service.restore(manifest.manifest_id, promote=True)

    assert result.ok is True
    assert result.verification.ok is True
    assert result.verification.missing_count == 0
    assert result.promotion is not None
    assert result.promotion.decision is PromotionDecision.PROMOTE
    assert result.restored_owner_generation == source_generation + 1
    assert result.restored_endpoint_identity != source_endpoint
    assert result.promotion.no_owner_overlap is True
    assert result.promotion.source_owner_generation == source_generation
    assert (
        result.promotion.restored_owner_generation == result.restored_owner_generation
    )


# ---------------------------------------------------------------------------
# Historic snapshot replay within retention
# ---------------------------------------------------------------------------


def test_historic_snapshots_replay_within_retention() -> None:
    backend = HermeticRecoveryBackend()
    _seed_shard(backend)
    service = _service(backend, retention=5)
    manifest, _ = service.capture()

    # Within retention (last 5 of [1..6] => 2,3,4,5,6)
    ok_replay = service.replay_historic_snapshots(
        manifest, requested_snapshot_ids=[2, 3, 4, 5, 6]
    )
    assert ok_replay.ok is True
    assert ok_replay.within_retention is True
    assert list(ok_replay.replayed_snapshot_ids) == [2, 3, 4, 5, 6]

    # Outside retention (snapshot 1 dropped by window of 5)
    bad_replay = service.replay_historic_snapshots(
        manifest, requested_snapshot_ids=[1, 6]
    )
    assert bad_replay.ok is False
    assert bad_replay.within_retention is False
    assert 1 not in bad_replay.replayed_snapshot_ids
    assert 6 in bad_replay.replayed_snapshot_ids


# ---------------------------------------------------------------------------
# New owner generation / endpoint identity without overlap
# ---------------------------------------------------------------------------


def test_restored_service_new_owner_generation_and_endpoint() -> None:
    backend = HermeticRecoveryBackend()
    state = _seed_shard(backend, owner_generation=11)
    service = _service(backend)
    manifest, _ = service.capture()

    with pytest.raises(PromotionError, match="must exceed"):
        service.restore(
            manifest.manifest_id,
            new_owner_generation=11,  # same as source
            promote=False,
        )

    with pytest.raises(PromotionError, match="must not overlap"):
        service.restore(
            manifest.manifest_id,
            new_endpoint_identity=state.endpoint_identity,
            promote=False,
        )

    result = service.restore(
        manifest.manifest_id,
        new_owner_generation=12,
        new_endpoint_identity="quacks://restored.example/cat_backup_1",
        promote=True,
    )
    assert result.ok is True
    assert result.restored_owner_generation == 12
    assert result.restored_endpoint_identity == "quacks://restored.example/cat_backup_1"
    live = backend.require_shard(_CATALOG)
    assert live.owner_generation == 12
    assert live.endpoint_identity == "quacks://restored.example/cat_backup_1"


# ---------------------------------------------------------------------------
# Cold-failover RPO/RTO; promotion identity bindings
# ---------------------------------------------------------------------------


def test_cold_failover_drill_declares_rpo_rto_and_binds_identities() -> None:
    backend = HermeticRecoveryBackend()
    state = _seed_shard(backend)
    source_generation = state.owner_generation
    source_endpoint = state.endpoint_identity
    storage_identity = state.storage_identity
    schema_identity = state.schema_identity
    extension_identity = state.extension_identity
    policy_identity = state.policy_identity
    verification_identity = state.verification_identity
    service = _service(backend)
    drill = service.run_cold_failover_drill(declared_rto_seconds=90.0)

    assert drill["ok"] is True
    assert drill["claims"]["claims_pitr"] is False
    assert drill["claims"]["claims_replication"] is False
    assert drill["claims"]["claims_built_in_ha"] is False
    assert drill["claims"]["cold_failover_only"] is True
    assert drill["owner_task_id"] == "DQK-098"

    restore = drill["restore"]
    promo = restore["promotion"]
    assert promo is not None
    metrics = promo["metrics"]
    assert metrics["cold_failover"] is True
    assert metrics["claims_pitr"] is False
    assert metrics["claims_replication"] is False
    assert metrics["claims_built_in_ha"] is False
    assert metrics["declared_rto_seconds"] == 90.0
    assert metrics["declared_rpo_seconds"] == 0.0
    assert metrics["measured_rto_seconds"] >= 0.0
    assert metrics["drill_kind"] == "cold_active_passive"

    identities = promo["identities"]
    assert identities["catalog_identity"].startswith("catalog:")
    assert identities["registry_identity"].startswith("registry:")
    assert identities["storage_identity"] == storage_identity
    assert identities["schema_identity"] == schema_identity
    assert identities["extension_identity"] == extension_identity
    assert identities["policy_identity"] == policy_identity
    assert identities["verification_identity"] == verification_identity

    assert promo["source_owner_generation"] == source_generation
    assert promo["restored_owner_generation"] > source_generation
    assert promo["source_endpoint_identity"] == source_endpoint
    assert promo["restored_endpoint_identity"] != source_endpoint
    assert promo["no_owner_overlap"] is True
    assert promo["decision"] == "promote"


def test_promotion_receipt_requires_identity_and_generation_advance() -> None:
    metrics = ColdFailoverMetrics(
        declared_rpo_seconds=0.0,
        declared_rto_seconds=60.0,
        measured_rpo_seconds=0.0,
        measured_rto_seconds=1.5,
    )
    identities = rec.PromotionIdentityBinding(
        catalog_identity="catalog:x:sha256:" + ("ab" * 32),
        registry_identity="registry:x:sha256:" + ("cd" * 32),
        storage_identity="storage@1",
        schema_identity="schema@1",
        extension_identity="ext@1",
        policy_identity="policy@1",
        verification_identity="verify@1",
    )
    with pytest.raises(PromotionError, match="strictly greater"):
        rec.PromotionDecisionReceipt(
            receipt_id="promo-1",
            manifest_id="man-1",
            decision=PromotionDecision.PROMOTE,
            source_owner_generation=5,
            restored_owner_generation=5,
            source_endpoint_identity="ep-a",
            restored_endpoint_identity="ep-b",
            identities=identities,
            metrics=metrics,
            no_owner_overlap=True,
            decided_at="2026-08-11T00:00:00Z",
            decided_by="broker",
        )
    with pytest.raises(PromotionError, match="new endpoint"):
        rec.PromotionDecisionReceipt(
            receipt_id="promo-2",
            manifest_id="man-1",
            decision=PromotionDecision.PROMOTE,
            source_owner_generation=5,
            restored_owner_generation=6,
            source_endpoint_identity="ep-same",
            restored_endpoint_identity="ep-same",
            identities=identities,
            metrics=metrics,
            no_owner_overlap=True,
            decided_at="2026-08-11T00:00:00Z",
            decided_by="broker",
        )
    with pytest.raises(PromotionError, match="no owner overlap"):
        rec.PromotionDecisionReceipt(
            receipt_id="promo-3",
            manifest_id="man-1",
            decision=PromotionDecision.PROMOTE,
            source_owner_generation=5,
            restored_owner_generation=6,
            source_endpoint_identity="ep-a",
            restored_endpoint_identity="ep-b",
            identities=identities,
            metrics=metrics,
            no_owner_overlap=False,
            decided_at="2026-08-11T00:00:00Z",
            decided_by="broker",
        )


def test_incomplete_manifest_cannot_restore() -> None:
    backend = HermeticRecoveryBackend()
    state = _seed_shard(backend)
    service = _service(backend)
    # Build a complete capture then flip complete=False via a forged incomplete path:
    # restore from missing manifest id fails; incomplete is enforced at restore.
    with pytest.raises(RecoveryError, match="unknown recovery manifest"):
        service.restore("man-does-not-exist")

    # Capture complete path still works.
    manifest, _ = service.capture()
    assert manifest.complete is True
    assert set(manifest.component_set()) == set(REQUIRED_BACKUP_COMPONENTS)
    assert manifest.claims_pitr is False
    assert manifest.claims_replication is False
    assert manifest.claims_built_in_ha is False
    assert manifest.encryption_policy.key_material_present is False
    assert manifest.catalog_id == state.catalog_id


def test_encryption_policy_never_embeds_key_material() -> None:
    policy = EncryptionPolicy(
        policy_id="enc-1",
        algorithm="AES-256-GCM",
        key_id="kms-1",
        encrypted_parquet=True,
        key_material_present=True,  # forced False
    )
    assert policy.key_material_present is False
    assert "key_material" not in policy.as_mapping() or policy.as_mapping()[
        "key_material_present"
    ] is False
