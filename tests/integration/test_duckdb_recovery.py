"""Integration tests for DuckDB recovery workflows (DQK-047).

Acceptance coverage:

* Restore proves schema and snapshot digests
* Retention cannot delete referenced evidence
* Recovery does not rely on cross-database atomicity

Also covers workload-aware checkpoint/backup/restore/verify/compact/retention
with quiescence, fencing, and disaster receipts.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOCAL_ACCELERATE = (_REPO_ROOT / "ipfs_accelerate_py").resolve()
_RECOVERY_MODULE = _REPO_ROOT / "ipfs_datasets_py/duckdb_control/recovery.py"


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

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.duckdb_control.connections import WorkloadKind
from ipfs_datasets_py.duckdb_control.recovery import (
    BACKUP_MANIFEST_SCHEMA,
    CHECKPOINT_SCHEMA,
    CRASH_BOUNDARIES,
    DISASTER_RECEIPT_SCHEMA,
    OWNER_TASK_ID,
    PROGRAM_ID,
    RECOVERY_SCHEMA,
    RESTORE_PROOF_SCHEMA,
    CrashInjected,
    ImmutableObjectRef,
    LogicalDatabaseState,
    MemoryRecoveryBackend,
    RecoveryError,
    RecoveryOrchestrator,
    RetentionBlockedError,
    RetentionPolicy,
    build_recovery_orchestrator,
    install_check,
    schema_digest_for_state,
    self_check,
    snapshot_digest_for_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _obj(label: str, *, media_type: str = "parquet", size: int = 32) -> ImmutableObjectRef:
    return ImmutableObjectRef(
        object_digest="sha256:" + hashlib.sha256(label.encode("utf-8")).hexdigest(),
        media_type=media_type,
        size_bytes=size,
        cid=f"cid-{label}" if label.isidentifier() else "",
    )


def _control_state(
    *,
    database_id: str = "db:control",
    objects: tuple[ImmutableObjectRef, ...] | None = None,
    generation: int = 1,
) -> LogicalDatabaseState:
    return LogicalDatabaseState(
        database_id=database_id,
        workload=WorkloadKind.CONTROL,
        schema_version="control-schema@1",
        tables={
            "tasks": (
                {"task_id": "DQK-047", "status": "ready"},
                {"task_id": "DQK-046", "status": "done"},
            ),
            "leases": ({"lease_id": "lease-1", "holder": "daemon-a"},),
        },
        referenced_objects=objects if objects is not None else (_obj("control-evidence"),),
        generation=generation,
    )


def _analytical_state(
    *,
    database_id: str = "db:analytical",
    objects: tuple[ImmutableObjectRef, ...] | None = None,
    generation: int = 1,
) -> LogicalDatabaseState:
    return LogicalDatabaseState(
        database_id=database_id,
        workload=WorkloadKind.ANALYTICAL,
        schema_version="analytical-schema@1",
        tables={
            "facts": (
                {"k": "alpha", "v": 1},
                {"k": "beta", "v": 2},
            )
        },
        referenced_objects=objects if objects is not None else (_obj("analytical-evidence"),),
        generation=generation,
    )


def _seeded_orchestrator(
    *states: LogicalDatabaseState,
    policy: RetentionPolicy | None = None,
) -> tuple[RecoveryOrchestrator, MemoryRecoveryBackend]:
    backend = MemoryRecoveryBackend()
    for state in states:
        backend.put_live_state(state)
    orch = build_recovery_orchestrator(backend, retention_policy=policy)
    return orch, backend


# ---------------------------------------------------------------------------
# Install / inert import / non-claims
# ---------------------------------------------------------------------------


def test_import_is_inert_and_install_check() -> None:
    report = install_check()
    assert report["ok"] is True
    assert report["owner_task_id"] == OWNER_TASK_ID
    assert report["program_id"] == PROGRAM_ID
    assert report["atomic_across_databases"] is False
    assert report["claims_cross_database_atomicity"] is False
    assert report["cross_database_atomicity_claim"] is False
    assert report["restore_proves_schema_and_snapshot_digests"] is True
    assert report["protect_referenced_evidence"] is True
    assert set(report["workflows"]) == {
        "checkpoint",
        "backup",
        "restore",
        "verify",
        "compact",
        "retention",
    }
    assert report["crash_boundaries"] == list(CRASH_BOUNDARIES)
    assert report["disaster_receipt_schema"] == DISASTER_RECEIPT_SCHEMA
    assert report["checkpoint_schema"] == CHECKPOINT_SCHEMA
    assert report["backup_manifest_schema"] == BACKUP_MANIFEST_SCHEMA
    assert report["restore_proof_schema"] == RESTORE_PROOF_SCHEMA


def test_no_cross_database_atomicity_claims_in_source() -> None:
    source = _RECOVERY_MODULE.read_text(encoding="utf-8")
    positive = [
        r"atomic_across_databases\s*=\s*True\b",
        r"claims_cross_database_atomicity\s*=\s*True\b",
        r"cross[_-]database\s+atomic(?:ity)?\s+is\s+(?:guaranteed|supported|provided)",
        r"guarantees?\s+cross[_-]database\s+atomic",
        r"relies?\s+on\s+cross[_-]database\s+atomic",
    ]
    for pattern in positive:
        assert re.search(pattern, source, re.IGNORECASE) is None, pattern
    assert "_CROSS_DATABASE_ATOMICITY_CLAIM: Final[bool] = False" in source
    assert "_ATOMIC_ACROSS_DATABASES: Final[bool] = False" in source
    assert "atomic_across_databases: Final[bool] = False" in source
    assert "claims_cross_database_atomicity: Final[bool] = False" in source


def test_self_check_passes() -> None:
    report = self_check(run_crash_recovery=True)
    assert report["ok"] is True, report.get("error")
    assert report["restore_proves_schema_and_snapshot_digests"] is True
    assert report["retention_cannot_delete_referenced_evidence"] is True
    assert report["recovery_does_not_rely_on_cross_database_atomicity"] is True
    assert report["backup_non_atomic"] is True
    assert report["atomic_across_databases"] is False


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


def test_schema_and_snapshot_digests_are_stable_and_distinct() -> None:
    state = _control_state()
    schema_a = schema_digest_for_state(state)
    snap_a = snapshot_digest_for_state(state)
    assert schema_a.startswith("sha256:")
    assert snap_a.startswith("sha256:")
    assert schema_a != snap_a
    # Stable.
    assert schema_digest_for_state(state) == schema_a
    assert snapshot_digest_for_state(state) == snap_a
    # Schema digest ignores row value changes that keep columns; snapshot does not.
    mutated = LogicalDatabaseState(
        database_id=state.database_id,
        workload=state.workload,
        schema_version=state.schema_version,
        tables={
            "tasks": (
                {"task_id": "DQK-047", "status": "running"},
                {"task_id": "DQK-046", "status": "done"},
            ),
            "leases": ({"lease_id": "lease-1", "holder": "daemon-a"},),
        },
        referenced_objects=state.referenced_objects,
        generation=state.generation,
    )
    assert schema_digest_for_state(mutated) == schema_a
    assert snapshot_digest_for_state(mutated) != snap_a


# ---------------------------------------------------------------------------
# Checkpoint / quiescence / fencing
# ---------------------------------------------------------------------------


def test_checkpoint_requires_quiescence_and_advances_fence() -> None:
    orch, backend = _seeded_orchestrator(_control_state())
    backend.set_handles("db:control", writers=2, readers=1, maintenance=0)
    with pytest.raises(RecoveryError, match="not quiescent"):
        orch.checkpoint("db:control", operation_id="op:ckpt:busy", force_drain=False)

    before = backend.get_fence("db:control")
    assert before is not None
    record = orch.checkpoint("db:control", operation_id="op:ckpt:ok", force_drain=True)
    assert record.SCHEMA == CHECKPOINT_SCHEMA
    assert record.database_id == "db:control"
    assert record.workload is WorkloadKind.CONTROL
    assert record.atomic_across_databases is False
    assert record.quiescence.quiescent is True
    assert record.fence.fencing_token > before.fencing_token
    assert record.schema_digest == schema_digest_for_state(_control_state())
    assert record.snapshot_digest == snapshot_digest_for_state(_control_state())


def test_checkpoint_is_idempotent_for_same_operation_id() -> None:
    orch, _ = _seeded_orchestrator(_control_state())
    a = orch.checkpoint("db:control", operation_id="op:ckpt:idem")
    b = orch.checkpoint("db:control", operation_id="op:ckpt:idem")
    assert a.checkpoint_id == b.checkpoint_id
    assert a.snapshot_digest == b.snapshot_digest


def test_workload_profile_rejects_mismatched_workload() -> None:
    from ipfs_datasets_py.duckdb_control.recovery import WorkloadProfile

    orch, _ = _seeded_orchestrator(_control_state())
    profile = WorkloadProfile(
        workload=WorkloadKind.ANALYTICAL,
        catalog_name="db:control",
        database_id="db:control",
    )
    with pytest.raises(RecoveryError, match="workload mismatch"):
        orch.checkpoint(
            "db:control",
            operation_id="op:ckpt:mismatch",
            profile=profile,
        )


def test_publication_workload_disallows_live_checkpoint() -> None:
    from ipfs_datasets_py.duckdb_control.recovery import WorkloadProfile

    state = LogicalDatabaseState(
        database_id="db:pub",
        workload=WorkloadKind.PUBLICATION,
        schema_version="pub@1",
        tables={"exports": ({"path": "exports/a.json"},)},
        referenced_objects=(),
        generation=1,
    )
    orch, _ = _seeded_orchestrator(state)
    profile = WorkloadProfile(
        workload=WorkloadKind.PUBLICATION,
        catalog_name="db:pub",
        database_id="db:pub",
    )
    assert profile.allow_live_checkpoint is False
    with pytest.raises(RecoveryError, match="does not allow live checkpoint"):
        orch.checkpoint("db:pub", operation_id="op:ckpt:pub", profile=profile)


# ---------------------------------------------------------------------------
# Backup / disaster receipt / non-atomicity
# ---------------------------------------------------------------------------


def test_backup_is_sequential_and_non_atomic_across_databases() -> None:
    control = _control_state(objects=(_obj("c-ev"),))
    analytical = _analytical_state(objects=(_obj("a-ev"),))
    orch, backend = _seeded_orchestrator(control, analytical)

    manifest, disaster = orch.backup(
        ("db:control", "db:analytical"),
        operation_id="op:backup:multi",
        force_drain=True,
    )
    assert manifest.SCHEMA == BACKUP_MANIFEST_SCHEMA
    assert manifest.atomic_across_databases is False
    assert "no_cross_database_atomicity" in manifest.notes
    assert set(manifest.database_ids) == {"db:control", "db:analytical"}
    assert len(manifest.checkpoint_ids) == 2
    assert disaster.SCHEMA == DISASTER_RECEIPT_SCHEMA
    assert disaster.atomic_across_databases is False
    assert disaster.claims_cross_database_atomicity is False
    assert disaster.backup_id == manifest.backup_id
    assert disaster.schema_digests["db:control"] == schema_digest_for_state(control)
    assert disaster.snapshot_digests["db:analytical"] == snapshot_digest_for_state(
        analytical
    )
    # Independent checkpoints exist even as separate records.
    for cid in manifest.checkpoint_ids:
        assert backend.get_checkpoint(cid) is not None


def test_backup_idempotent_under_same_operation_id() -> None:
    orch, _ = _seeded_orchestrator(_control_state(), _analytical_state())
    m1, d1 = orch.backup(
        ("db:control", "db:analytical"), operation_id="op:backup:idem"
    )
    m2, d2 = orch.backup(
        ("db:control", "db:analytical"), operation_id="op:backup:idem"
    )
    assert m1.backup_id == m2.backup_id
    assert d1.receipt_id == d2.receipt_id


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def test_verify_confirms_schema_snapshot_and_objects() -> None:
    orch, backend = _seeded_orchestrator(_control_state(), _analytical_state())
    manifest, _ = orch.backup(
        ("db:control", "db:analytical"), operation_id="op:verify:bak"
    )
    receipt = orch.verify(manifest.backup_id, operation_id="op:verify:1")
    assert receipt.ok is True
    assert all(receipt.checked_schema_digests.values())
    assert all(receipt.checked_snapshot_digests.values())
    assert receipt.missing_objects == ()

    # Missing object fails verify.
    obj = manifest.object_inventory[0]
    backend.put_object(obj, present=False)
    bad = orch.verify(manifest.backup_id, operation_id="op:verify:missing")
    assert bad.ok is False
    assert obj.object_digest in bad.missing_objects


# ---------------------------------------------------------------------------
# Restore proves digests
# ---------------------------------------------------------------------------


def test_restore_proves_schema_and_snapshot_digests() -> None:
    control = _control_state(objects=(_obj("rest-c"),))
    analytical = _analytical_state(objects=(_obj("rest-a"),))
    orch, backend = _seeded_orchestrator(control, analytical)
    manifest, _ = orch.backup(
        ("db:control", "db:analytical"), operation_id="op:restore:bak"
    )

    result = orch.restore(
        manifest.backup_id,
        target_map={
            "db:control": "db:control-restored",
            "db:analytical": "db:analytical-restored",
        },
        operation_id="op:restore:1",
    )
    assert result.ok is True, result.error
    assert result.atomic_across_databases is False
    assert set(result.target_database_ids) == {
        "db:control-restored",
        "db:analytical-restored",
    }
    assert len(result.proofs) == 2
    for proof in result.proofs:
        assert proof.ok is True
        assert proof.expected_schema_digest == proof.actual_schema_digest
        assert proof.expected_snapshot_digest == proof.actual_snapshot_digest
        assert proof.mismatches == ()
        assert proof.SCHEMA == RESTORE_PROOF_SCHEMA

    restored = backend.get_restored_state("db:control-restored")
    assert restored is not None
    assert restored.tables["tasks"][0]["task_id"] == "DQK-047"
    assert result.disaster_receipt_cid.startswith("sha256:")


def test_restore_fails_closed_when_snapshot_digest_mismatches() -> None:
    orch, backend = _seeded_orchestrator(_control_state())
    manifest, _ = orch.backup(("db:control",), operation_id="op:restore:tamper-bak")

    # Tamper checkpoint payload after backup (simulates corruption).
    ckpt = backend.get_checkpoint(manifest.checkpoint_ids[0])
    assert ckpt is not None
    payload = dict(ckpt.state_payload)
    tables = dict(payload["tables"])
    tables["tasks"] = [{"task_id": "TAMPERED", "status": "evil"}]
    payload["tables"] = tables
    from ipfs_datasets_py.duckdb_control.recovery import (
        CheckpointRecord,
        QuiescenceState,
        WriterFence,
    )

    tampered = CheckpointRecord(
        checkpoint_id=ckpt.checkpoint_id,
        database_id=ckpt.database_id,
        workload=ckpt.workload,
        schema_digest=ckpt.schema_digest,  # stale declared digest
        snapshot_digest=ckpt.snapshot_digest,  # stale declared digest
        object_digests=ckpt.object_digests,
        fence=ckpt.fence,
        quiescence=ckpt.quiescence,
        generation=ckpt.generation,
        created_at=ckpt.created_at,
        operation_id=ckpt.operation_id,
        state_payload=payload,
    )
    backend.put_checkpoint(tampered)

    # Verify should catch mismatch (recomputed digests != declared).
    verify = orch.verify(manifest.backup_id, operation_id="op:restore:tamper-verify")
    assert verify.ok is False

    result = orch.restore(manifest.backup_id, operation_id="op:restore:tamper")
    assert result.ok is False
    assert "verification failed" in result.error or result.error


# ---------------------------------------------------------------------------
# Retention cannot delete referenced evidence
# ---------------------------------------------------------------------------


def test_retention_cannot_delete_referenced_evidence() -> None:
    evidence = _obj("protected-evidence")
    orch, backend = _seeded_orchestrator(
        _control_state(objects=(evidence,)),
        policy=RetentionPolicy(
            max_checkpoints_per_database=50,
            max_backups=50,
            dry_run_default=False,
        ),
    )
    orch.backup(("db:control",), operation_id="op:ret:bak")
    assert backend.has_object(evidence.object_digest)

    with pytest.raises(RetentionBlockedError) as excinfo:
        orch.retention(
            dry_run=False,
            force_delete_objects=(evidence.object_digest,),
            operation_id="op:ret:block",
        )
    assert excinfo.value.object_digest == evidence.object_digest
    assert excinfo.value.referrers
    assert backend.has_object(evidence.object_digest)

    # Direct backend delete also fails closed.
    with pytest.raises(RetentionBlockedError):
        backend.delete_object(evidence.object_digest)


def test_retention_dry_run_reports_protection_without_deletion() -> None:
    evidence = _obj("dry-run-evidence")
    orch, backend = _seeded_orchestrator(_control_state(objects=(evidence,)))
    orch.backup(("db:control",), operation_id="op:ret:dry-bak")

    receipt = orch.retention(
        dry_run=True,
        force_delete_objects=(evidence.object_digest,),
        operation_id="op:ret:dry",
    )
    assert receipt.dry_run is True
    assert (
        evidence.object_digest in receipt.protected_object_digests
        or evidence.object_digest in receipt.blocked_artifact_ids
    )
    assert backend.has_object(evidence.object_digest)


def test_retention_can_remove_unreferenced_object() -> None:
    orphan = _obj("orphan-object")
    orch, backend = _seeded_orchestrator(_control_state(objects=()))
    backend.put_object(orphan, present=True)
    # No evidence references orphan.
    assert backend.list_evidence(orphan.object_digest) == []

    receipt = orch.retention(
        dry_run=False,
        force_delete_objects=(orphan.object_digest,),
        operation_id="op:ret:orphan",
        policy=RetentionPolicy(max_checkpoints_per_database=50, max_backups=50),
    )
    assert orphan.object_digest in receipt.removed_artifact_ids
    assert not backend.has_object(orphan.object_digest)


def test_retention_keeps_checkpoints_referenced_by_backups() -> None:
    orch, backend = _seeded_orchestrator(
        _control_state(),
        policy=RetentionPolicy(max_checkpoints_per_database=1, max_backups=10),
    )
    # Create extra checkpoints then a backup that pins the latest.
    orch.checkpoint("db:control", operation_id="op:ret:ckpt1")
    orch.checkpoint("db:control", operation_id="op:ret:ckpt2")
    manifest, _ = orch.backup(("db:control",), operation_id="op:ret:bak-pin")
    pinned = set(manifest.checkpoint_ids)

    receipt = orch.retention(dry_run=False, operation_id="op:ret:apply")
    for cid in pinned:
        assert backend.get_checkpoint(cid) is not None
        assert cid not in receipt.removed_artifact_ids or cid in receipt.blocked_artifact_ids


# ---------------------------------------------------------------------------
# Compact
# ---------------------------------------------------------------------------


def test_compact_dry_run_default_and_protects_backup_checkpoints() -> None:
    orch, backend = _seeded_orchestrator(_control_state())
    for i in range(5):
        orch.checkpoint("db:control", operation_id=f"op:compact:ckpt:{i}")
    manifest, _ = orch.backup(("db:control",), operation_id="op:compact:bak")

    dry = orch.compact("db:control", keep_checkpoints=2, dry_run=True)
    assert dry.dry_run is True
    # Dry-run does not delete.
    assert len(backend.list_checkpoints("db:control")) >= 5

    wet = orch.compact("db:control", keep_checkpoints=2, dry_run=False)
    assert wet.dry_run is False
    remaining = {c.checkpoint_id for c in backend.list_checkpoints("db:control")}
    for cid in manifest.checkpoint_ids:
        assert cid in remaining


# ---------------------------------------------------------------------------
# Crash injection / recovery
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "boundary",
    [
        "before_checkpoint",
        "after_checkpoint",
        "before_backup",
        "after_backup",
        "before_restore_materialize",
        "after_restore_materialize",
        "before_restore_prove",
        "after_restore_prove",
    ],
)
def test_crash_injection_is_idempotently_recoverable(boundary: str) -> None:
    backend = MemoryRecoveryBackend()
    orch = build_recovery_orchestrator(backend)
    state = _control_state(database_id="db:crash")
    backend.put_live_state(state)

    op = f"op:crash:{boundary}"
    orch.set_crash_at(boundary)
    with pytest.raises(CrashInjected) as excinfo:
        if "restore" in boundary:
            # Need a backup first without crash.
            orch.set_crash_at(None)
            man, _ = orch.backup(("db:crash",), operation_id=f"{op}:pre")
            orch.set_crash_at(boundary)
            orch.restore(man.backup_id, operation_id=op)
        elif "backup" in boundary:
            orch.backup(("db:crash",), operation_id=op)
        else:
            orch.checkpoint("db:crash", operation_id=op)
    assert excinfo.value.boundary == boundary

    orch.set_crash_at(None)
    if "restore" in boundary:
        man = backend.list_backups()[0]
        result = orch.restore(man.backup_id, operation_id=op)
        assert result.ok is True
        assert result.atomic_across_databases is False
    elif "backup" in boundary:
        manifest, disaster = orch.backup(("db:crash",), operation_id=op)
        assert disaster.claims_cross_database_atomicity is False
        assert manifest.atomic_across_databases is False
    else:
        record = orch.checkpoint("db:crash", operation_id=op)
        assert record.atomic_across_databases is False


# ---------------------------------------------------------------------------
# Multi-database independence
# ---------------------------------------------------------------------------


def test_multi_database_restore_is_independent_not_atomic() -> None:
    """Failure on one database must not imply multi-DB transactional rollback."""

    orch, backend = _seeded_orchestrator(_control_state(), _analytical_state())
    manifest, disaster = orch.backup(
        ("db:control", "db:analytical"), operation_id="op:indep:bak"
    )
    assert disaster.atomic_across_databases is False

    # Delete only analytical checkpoint to simulate partial corruption.
    for cid in list(manifest.checkpoint_ids):
        ckpt = backend.get_checkpoint(cid)
        if ckpt and ckpt.database_id == "db:analytical":
            backend.delete_checkpoint(cid)

    # Verify fails, restore fails closed before partial authority acceptance
    # of the whole set — but the design is sequential proofs, not multi-DB txn.
    verify = orch.verify(manifest.backup_id, operation_id="op:indep:verify")
    assert verify.ok is False

    result = orch.restore(manifest.backup_id, operation_id="op:indep:restore")
    assert result.ok is False
    assert result.atomic_across_databases is False


def test_orchestrator_constants_deny_cross_database_atomicity() -> None:
    orch, _ = _seeded_orchestrator(_control_state())
    assert orch.atomic_across_databases is False
    assert orch.claims_cross_database_atomicity is False
    assert RecoveryOrchestrator.atomic_across_databases is False
    assert RecoveryOrchestrator.claims_cross_database_atomicity is False


def test_schema_constants_match_program() -> None:
    assert OWNER_TASK_ID == "DQK-047"
    assert PROGRAM_ID == "ipfs-datasets-duckdb-quack-v1"
    assert RECOVERY_SCHEMA.startswith("ipfs_datasets_py/duckdb-control-recovery")
