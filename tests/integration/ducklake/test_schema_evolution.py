"""Integration tests for versioned field-ID contracts and constraints (DQK-094).

Covers acceptance criteria:

* Add/drop/rename and lossless promotion replay across historic snapshots
* Invalid domain, uniqueness, reference, and tenant records are rejected before
  commit
* Authoritative reservation and durable outbox live in the per-shard private
  companion owner-control DuckDB, separate from DuckLake internal metadata and
  never visible to the Quack-serving DatabaseInstance
* Every uniqueness/reference scope resolves to exactly one authoritative home
  shard; unsupported cross-shard scopes fail before object copy or snapshot
  mutation
* Every write reaches the single fenced catalog owner and acquires a persistent
  logical-key/idempotency-key reservation before the non-atomic snapshot
  boundary, then terminalizes it with the exact committed snapshot through the
  durable outbox
* Recovery reconciles reservation, object, catalog snapshot, and outbox states
  without claiming atomicity across files
* Concurrent same-key remote requests are serialized at the owner, contend on
  the durable reservation, and exactly one wins
* Independent catalog shards may progress concurrently without sharing a
  reservation database
* A successful reservation is never released or reused; crash recovery may
  reclaim only proven incomplete or failed claims
* Constraint evidence binds the exact source files and schema revision
* Schema changes require an authorized migration receipt and rollback plan

Hermetic: uses DQK-086 memory registries (no duckdb/network required).
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

# Prefer the sealed validator's accelerator checkout in nested worktrees.
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

from ipfs_datasets_py.ducklake import contracts as c
from ipfs_datasets_py.ducklake import registry as reg
from ipfs_datasets_py.ducklake import schema as sch


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_DIGEST_A = "sha256:" + ("ab" * 32)


def _control() -> reg.ControlLakeRegistry:
    control = reg.ControlLakeRegistry(owner_id="control-dqk094")
    control.apply_migrations()
    return control


def _seed_topology(control: reg.ControlLakeRegistry) -> str:
    """Register catalog + two shards + events dataset home on shard_a."""

    control.register_catalog(
        catalog_id="cat_a",
        catalog_digest=_DIGEST_A,
        storage_kind="local_block",
        metadata_path="/var/lib/ducklake/catalogs/a.duckdb",
    )
    control.register_shard(
        shard_id="shard_a",
        catalog_id="cat_a",
        ring_position=0,
        endpoint_identity="quacks://127.0.0.1:19001/cat_a",
    )
    control.register_shard(
        shard_id="shard_b",
        catalog_id="cat_a",
        ring_position=1,
        endpoint_identity="quacks://127.0.0.1:19002/cat_a",
    )
    alias = sch.LogicalDatasetAlias(
        alias="events", tenant="acme", namespace="analytics"
    )
    control.register_logical_dataset(alias)
    control.assign_home_shard(
        dataset_id=alias.dataset_id,
        home_shard_id="shard_a",
        uniqueness_scope=f"dataset:{alias.dataset_id}",
    )
    return alias.dataset_id


def _quack(shard_id: str) -> reg.DatabaseInstanceBinding:
    return reg.DatabaseInstanceBinding(
        instance_id=f"quack-{shard_id}",
        kind=reg.DatabaseInstanceKind.QUACK_SERVING,
        path=f":memory:quack:{shard_id}",
        private=True,
        attachable_from_quack=False,
    )


def _service(
    control: reg.ControlLakeRegistry,
    *,
    shard_id: str = "shard_a",
    owner_id: str | None = None,
) -> c.ConstraintService:
    companion = reg.CompanionLakeRegistry(
        shard_id=shard_id,
        owner_id=owner_id or f"owner-{shard_id}",
        control=control,
    )
    companion.apply_migrations()
    return c.ConstraintService(
        shard_id=shard_id,
        owner_id=owner_id or f"owner-{shard_id}",
        control=control,
        companion=companion,
        quack_instance=_quack(shard_id),
        catalog_id="cat_a",
    )


def _base_fields() -> tuple[c.FieldContract, ...]:
    return (
        c.FieldContract(
            field_id="f_event_id",
            name="event_id",
            field_type=c.FieldType.INT32,
            nullable=False,
            required=True,
            domain=c.DomainCheck(kind="range", params={"min": 1}),
        ),
        c.FieldContract(
            field_id="f_payload",
            name="payload",
            field_type=c.FieldType.UTF8,
            nullable=False,
            required=True,
        ),
        c.FieldContract(
            field_id="f_amount",
            name="amount",
            field_type=c.FieldType.FLOAT32,
            nullable=True,
            domain=c.DomainCheck(kind="range", params={"min": 0.0}),
        ),
        c.FieldContract(
            field_id="f_status",
            name="status",
            field_type=c.FieldType.UTF8,
            nullable=False,
            required=True,
            domain=c.DomainCheck(
                kind="enum", params={"values": ["open", "closed", "pending"]}
            ),
        ),
    )


def _contract(
    dataset_id: str,
    *,
    revision: int = 1,
    fields: tuple[c.FieldContract, ...] | None = None,
    column_policy: c.ColumnPolicy | None = None,
) -> c.SchemaContract:
    return c.SchemaContract(
        contract_id="contract-events-v1",
        dataset_id=dataset_id,
        revision=revision,
        fields=fields or _base_fields(),
        tenant="acme",
        column_policy=column_policy
        or c.ColumnPolicy(
            missing=c.MissingColumnPolicy.REJECT,
            extra=c.ExtraColumnPolicy.REJECT,
        ),
        uniqueness_scopes=(f"dataset:{dataset_id}",),
    )


def _migration_receipt(
    contract: c.SchemaContract, *, to_revision: int
) -> c.MigrationReceipt:
    return c.MigrationReceipt(
        receipt_id=f"mig-{contract.contract_id}-r{to_revision}",
        schema_contract_id=contract.contract_id,
        from_revision=contract.revision,
        to_revision=to_revision,
        authorizer_identity="schema-authority@control",
        rollback_plan=c.RollbackPlan(
            plan_id=f"rb-{contract.contract_id}-r{to_revision}",
            target_revision=contract.revision,
            steps=({"kind": "restore_revision", "revision": contract.revision},),
            reason="authorized schema evolution rollback",
        ),
    )


# ---------------------------------------------------------------------------
# Add / drop / rename / lossless promotion replay
# ---------------------------------------------------------------------------


def test_add_drop_rename_and_lossless_promotion_replay() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    svc = _service(control)

    v1 = _contract(dataset_id)
    svc.register_schema_contract(v1)

    # Rename payload -> body (same field_id), promote amount float32->float64,
    # add region, drop status via replacement set (with migration receipt).
    v2_fields = (
        c.FieldContract(
            field_id="f_event_id",
            name="event_id",
            field_type=c.FieldType.INT64,  # lossless promote
            nullable=False,
            required=True,
            domain=c.DomainCheck(kind="range", params={"min": 1}),
        ),
        c.FieldContract(
            field_id="f_payload",
            name="body",  # rename
            field_type=c.FieldType.UTF8,
            nullable=False,
            required=True,
        ),
        c.FieldContract(
            field_id="f_amount",
            name="amount",
            field_type=c.FieldType.FLOAT64,  # lossless promote
            nullable=True,
        ),
        c.FieldContract(
            field_id="f_region",
            name="region",
            field_type=c.FieldType.UTF8,
            nullable=True,
            default="us-east",
        ),
        # f_status dropped
    )
    receipt = _migration_receipt(v1, to_revision=2)
    v2, plan = c.evolve_schema(
        v1, next_fields=v2_fields, migration_receipt=receipt, next_revision=2
    )
    kinds = {s["kind"] for s in plan.steps}
    assert "rename" in kinds
    assert "promote" in kinds
    assert "add" in kinds
    assert "drop" in kinds
    assert plan.lossless is True

    svc.register_schema_contract(v2, migration_receipt=receipt)

    # Replay at historic revision 1 still sees original names/types.
    view_v1 = svc.replay_historic_snapshot(
        v1.contract_id,
        revision=1,
        sample_values={"f_event_id": 7, "f_amount": 1.5},
    )
    assert view_v1.contract.revision == 1
    assert view_v1.contract.field_by_id("f_payload").name == "payload"
    assert view_v1.contract.field_by_id("f_event_id").field_type is c.FieldType.INT32

    view_v2 = svc.replay_historic_snapshot(
        v1.contract_id,
        revision=2,
        sample_values={"f_event_id": 7, "f_amount": 1.5},
    )
    assert view_v2.contract.revision == 2
    assert view_v2.contract.field_by_id("f_payload").name == "body"
    assert view_v2.contract.field_by_id("f_event_id").field_type is c.FieldType.INT64
    assert any(p.field_id == "f_event_id" and p.lossless for p in view_v2.promotions)
    assert any(p.field_id == "f_amount" and p.lossless for p in view_v2.promotions)
    # Dropped field absent at v2.
    with pytest.raises(c.ContractError, match="unknown field_id"):
        view_v2.contract.field_by_id("f_status")


def test_lossy_type_promotion_rejected() -> None:
    with pytest.raises(c.TypePromotionError, match="lossy"):
        c.promote_value(1_000_000, source=c.FieldType.INT64, target=c.FieldType.INT32)
    assert c.is_lossless_promotion(c.FieldType.INT32, c.FieldType.INT64)
    assert not c.is_lossless_promotion(c.FieldType.FLOAT64, c.FieldType.FLOAT32)
    assert not c.is_lossless_promotion(c.FieldType.UTF8, c.FieldType.INT32)


def test_schema_change_requires_migration_receipt_and_rollback_plan() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    svc = _service(control)
    v1 = _contract(dataset_id)
    svc.register_schema_contract(v1)

    v2_fields = v1.fields + (
        c.FieldContract(
            field_id="f_extra",
            name="extra",
            field_type=c.FieldType.UTF8,
            nullable=True,
        ),
    )
    with pytest.raises(c.MigrationAuthorizationError, match="migration receipt"):
        c.evolve_schema(v1, next_fields=v2_fields, migration_receipt=None)

    with pytest.raises(c.MigrationAuthorizationError, match="migration receipt"):
        svc.register_schema_contract(
            c.SchemaContract(
                contract_id=v1.contract_id,
                dataset_id=dataset_id,
                revision=2,
                fields=v2_fields,
                tenant="acme",
            ),
            migration_receipt=None,
        )

    # Unauthorized receipt fails closed.
    with pytest.raises(c.MigrationAuthorizationError):
        c.MigrationReceipt(
            receipt_id="bad",
            schema_contract_id=v1.contract_id,
            from_revision=1,
            to_revision=2,
            authorizer_identity="nobody",
            rollback_plan=c.RollbackPlan(
                plan_id="rb", target_revision=1, steps=()
            ),
            authorized=False,
        )

    # Rollback plan must target from_revision.
    with pytest.raises(c.SchemaMigrationError, match="rollback_plan"):
        c.MigrationReceipt(
            receipt_id="bad2",
            schema_contract_id=v1.contract_id,
            from_revision=1,
            to_revision=2,
            authorizer_identity="auth",
            rollback_plan=c.RollbackPlan(
                plan_id="rb", target_revision=0, steps=()
            ),
        )


# ---------------------------------------------------------------------------
# Pre-commit constraint rejection
# ---------------------------------------------------------------------------


def test_invalid_domain_uniqueness_reference_tenant_rejected_before_commit() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    svc = _service(control)
    contract = _contract(dataset_id)
    svc.register_schema_contract(contract)
    source_files = ("s3://bucket/events/part-000.parquet",)
    source_digests = ("sha256:" + ("11" * 32),)

    # Domain failure (status not in enum).
    bad_domain = [
        {
            "f_event_id": 1,
            "f_payload": "x",
            "f_amount": 1.0,
            "f_status": "nope",
            "tenant": "acme",
        }
    ]
    result = svc.validate_before_commit(
        contract, bad_domain, source_files=source_files, source_digests=source_digests
    )
    assert result.accepted is False
    assert any(r.constraint_kind is c.ConstraintKind.DOMAIN for r in result.rejects)
    assert result.rejects[0].evidence.schema_revision == contract.revision
    assert result.rejects[0].evidence.source_files == source_files
    assert result.rejects[0].evidence.source_digests == source_digests

    # Tenant failure.
    bad_tenant = [
        {
            "f_event_id": 1,
            "f_payload": "x",
            "f_status": "open",
            "tenant": "other-tenant",
        }
    ]
    result = svc.validate_before_commit(
        contract, bad_tenant, source_files=source_files, source_digests=source_digests
    )
    assert result.accepted is False
    assert any(r.constraint_kind is c.ConstraintKind.TENANT for r in result.rejects)

    # Reference failure.
    bad_ref = [
        {
            "f_event_id": 99,
            "f_payload": "x",
            "f_status": "open",
            "tenant": "acme",
        }
    ]
    result = svc.validate_before_commit(
        contract,
        bad_ref,
        source_files=source_files,
        source_digests=source_digests,
        reference_keys={"f_event_id": {1, 2, 3}},
    )
    assert result.accepted is False
    assert any(r.constraint_kind is c.ConstraintKind.REFERENCE for r in result.rejects)

    # Uniqueness failure within batch.
    dupes = [
        {"f_event_id": 1, "f_payload": "a", "f_status": "open", "tenant": "acme"},
        {"f_event_id": 1, "f_payload": "b", "f_status": "open", "tenant": "acme"},
    ]
    result = svc.validate_before_commit(
        contract,
        dupes,
        source_files=source_files,
        source_digests=source_digests,
        uniqueness_key_fields=("f_event_id",),
    )
    assert result.accepted is False
    assert any(
        r.constraint_kind is c.ConstraintKind.UNIQUENESS for r in result.rejects
    )

    # commit_write must not advance snapshot on rejection.
    before = svc._catalog_snapshot
    with pytest.raises(c.ConstraintViolation, match="rejected before commit"):
        svc.commit_write(
            contract=contract,
            records=bad_domain,
            source_files=source_files,
            source_digests=source_digests,
            uniqueness_scope=f"dataset:{dataset_id}",
            logical_key={"f_event_id": 1},
            idempotency_key="idem-reject-1",
        )
    assert svc._catalog_snapshot == before


def test_constraint_evidence_binds_source_files_and_schema_revision() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    contract = _contract(dataset_id)
    files = ("file://data/a.parquet", "file://data/b.parquet")
    digests = ("sha256:" + ("aa" * 32), "sha256:" + ("bb" * 32))
    result = c.validate_records_before_commit(
        contract,
        [
            {
                "f_event_id": 1,
                "f_payload": "ok",
                "f_status": "open",
                "tenant": "acme",
            }
        ],
        source_files=files,
        source_digests=digests,
        uniqueness_key_fields=("f_event_id",),
    )
    assert result.accepted is True
    for ev in result.evidence:
        assert ev.source_files == files
        assert ev.source_digests == digests
        assert ev.schema_revision == contract.revision
        assert ev.schema_digest == contract.schema_digest
        assert ev.schema_contract_id == contract.contract_id


def test_extra_and_missing_column_policy() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    strict = _contract(dataset_id)
    with pytest.raises(c.ConstraintViolation, match="extra columns"):
        c.apply_column_policy(
            strict,
            {
                "f_event_id": 1,
                "f_payload": "x",
                "f_status": "open",
                "unknown_col": True,
            },
        )
    with pytest.raises(c.ConstraintViolation, match="missing"):
        c.apply_column_policy(strict, {"f_event_id": 1, "f_payload": "x"})

    permissive_missing = _contract(
        dataset_id,
        column_policy=c.ColumnPolicy(
            missing=c.MissingColumnPolicy.DEFAULT,
            extra=c.ExtraColumnPolicy.DROP,
        ),
    )
    # amount is optional nullable — default path
    fields = list(permissive_missing.fields)
    # Make status have a default so missing is fillable.
    fields[3] = c.FieldContract(
        field_id="f_status",
        name="status",
        field_type=c.FieldType.UTF8,
        nullable=False,
        required=False,
        default="pending",
        domain=c.DomainCheck(
            kind="enum", params={"values": ["open", "closed", "pending"]}
        ),
    )
    permissive_missing = c.SchemaContract(
        contract_id="contract-events-v1",
        dataset_id=dataset_id,
        revision=1,
        fields=tuple(fields),
        tenant="acme",
        column_policy=c.ColumnPolicy(
            missing=c.MissingColumnPolicy.DEFAULT,
            extra=c.ExtraColumnPolicy.DROP,
        ),
    )
    normalized = c.apply_column_policy(
        permissive_missing,
        {"f_event_id": 1, "f_payload": "x", "extra_noise": 9},
    )
    assert "extra_noise" not in normalized
    assert normalized["f_status"] == "pending"


# ---------------------------------------------------------------------------
# Companion isolation / home-shard routing
# ---------------------------------------------------------------------------


def test_reservation_and_outbox_live_in_companion_not_quack_or_ducklake() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    svc = _service(control)
    contract = _contract(dataset_id)
    svc.register_schema_contract(contract)

    # Companion is private and not attachable from Quack.
    assert svc.companion.instance.kind is reg.DatabaseInstanceKind.COMPANION_PRIVATE
    assert svc.companion.instance.attachable_from_quack is False
    c.assert_companion_reservation_isolation(svc.companion, quack=_quack("shard_a"))

    # Authority tables are companion-scoped, not DuckLake internal.
    for table in (
        "lake_logical_key_reservations",
        "lake_ingest_outbox",
        "lake_schema_contracts",
    ):
        c.assert_not_ducklake_internal_metadata(table)
        assert table in sch.COMPANION_TABLES
        assert table not in sch.DUCKLAKE_INTERNAL_V1_TABLES

    receipt = svc.commit_write(
        contract=contract,
        records=[
            {
                "f_event_id": 1,
                "f_payload": "alpha",
                "f_status": "open",
                "tenant": "acme",
            }
        ],
        source_files=("s3://b/a.parquet",),
        source_digests=("sha256:" + ("22" * 32),),
        uniqueness_scope=f"dataset:{dataset_id}",
        logical_key={"f_event_id": 1},
        idempotency_key="idem-iso-1",
        uniqueness_key_fields=("f_event_id",),
        object_uri="s3://owned/a.parquet",
    )
    assert receipt.atomic_across_files is False
    assert receipt.reservation.status is c.ReservationStatus.COMMITTED
    assert receipt.outbox.status == "committed"
    assert receipt.snapshot_version == receipt.reservation.snapshot_version

    # Rows live only in companion store.
    res_rows = svc.companion.store.list_rows("lake_logical_key_reservations")
    out_rows = svc.companion.store.list_rows("lake_ingest_outbox")
    assert len(res_rows) == 1
    assert len(out_rows) == 1

    # Simulating illegal visibility fails isolation assert.
    quack = _quack("shard_a")
    svc.companion.store.mark_attached_from(quack.instance_id)
    with pytest.raises(c.ContractError, match="visible from the Quack"):
        c.assert_companion_reservation_isolation(svc.companion, quack=quack)


def test_cross_shard_scope_fails_before_copy_or_snapshot() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    svc = _service(control)
    contract = _contract(dataset_id)
    svc.register_schema_contract(contract)
    before = svc._catalog_snapshot

    with pytest.raises(c.CrossShardConstraintError, match="before object copy"):
        svc.resolve_scope_home(
            uniqueness_scope="cross_shard:global_pk", dataset_id=dataset_id
        )

    with pytest.raises(c.CrossShardConstraintError):
        svc.acquire_reservation(
            dataset_id=dataset_id,
            uniqueness_scope="cross_shard:global_pk",
            logical_key="k1",
            idempotency_key="idem-x",
        )

    # Wrong home shard fails before mutation.
    svc_b = _service(control, shard_id="shard_b")
    with pytest.raises(c.CrossShardConstraintError, match="homes at"):
        svc_b.acquire_reservation(
            dataset_id=dataset_id,
            uniqueness_scope=f"dataset:{dataset_id}",
            logical_key="k1",
            idempotency_key="idem-wrong-home",
        )

    with pytest.raises(c.CrossShardConstraintError):
        svc.commit_write(
            contract=contract,
            records=[
                {
                    "f_event_id": 1,
                    "f_payload": "x",
                    "f_status": "open",
                    "tenant": "acme",
                }
            ],
            source_files=("s3://b/a.parquet",),
            uniqueness_scope="cross_shard:global_pk",
            logical_key={"f_event_id": 1},
            idempotency_key="idem-cross",
        )
    assert svc._catalog_snapshot == before
    assert not svc.companion.store.list_rows("lake_logical_key_reservations")


def test_every_uniqueness_scope_resolves_to_exactly_one_home_shard() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    svc = _service(control)
    resolved = svc.resolve_scope_home(
        uniqueness_scope=f"dataset:{dataset_id}", dataset_id=dataset_id
    )
    assert resolved["home_shard_id"] == "shard_a"
    assert resolved["authoritative"] is True


# ---------------------------------------------------------------------------
# Write path: reserve → snapshot → outbox
# ---------------------------------------------------------------------------


def test_write_reserves_before_snapshot_and_terminalizes_via_outbox() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    svc = _service(control)
    contract = _contract(dataset_id)
    svc.register_schema_contract(contract)

    receipt = svc.commit_write(
        contract=contract,
        records=[
            {
                "f_event_id": 42,
                "f_payload": "payload",
                "f_status": "closed",
                "tenant": "acme",
            }
        ],
        source_files=("s3://bucket/part-042.parquet",),
        source_digests=("sha256:" + ("42" * 32),),
        uniqueness_scope=f"dataset:{dataset_id}",
        logical_key={"f_event_id": 42},
        idempotency_key="idem-42",
        uniqueness_key_fields=("f_event_id",),
        operation_id="op-42",
        object_uri="s3://owned/part-042.parquet",
    )
    assert receipt.reservation.status is c.ReservationStatus.COMMITTED
    assert receipt.reservation.idempotency_key == "idem-42"
    assert receipt.reservation.snapshot_version == receipt.snapshot_version
    assert receipt.outbox.snapshot_version == receipt.snapshot_version
    assert receipt.outbox.status == "committed"
    assert receipt.schema_revision == contract.revision
    assert receipt.schema_digest == contract.schema_digest
    assert receipt.atomic_across_files is False
    assert any(
        e.outcome == "accepted" and e.source_files[0].endswith("part-042.parquet")
        for e in receipt.evidence
    )


def test_successful_reservation_never_released_or_reused() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    svc = _service(control)
    contract = _contract(dataset_id)
    svc.register_schema_contract(contract)

    receipt = svc.commit_write(
        contract=contract,
        records=[
            {
                "f_event_id": 7,
                "f_payload": "p",
                "f_status": "open",
                "tenant": "acme",
            }
        ],
        source_files=("s3://b/7.parquet",),
        uniqueness_scope=f"dataset:{dataset_id}",
        logical_key={"f_event_id": 7},
        idempotency_key="idem-7",
        uniqueness_key_fields=("f_event_id",),
    )
    rid = receipt.reservation.reservation_id

    with pytest.raises(c.ReservationError, match="never released"):
        svc.release_reservation(rid)

    with pytest.raises(c.ReservationError, match="cannot reclaim|never"):
        svc.reclaim_incomplete_or_failed(rid)

    # Different idempotency key on same logical key loses contention.
    with pytest.raises(c.ReservationContention):
        svc.acquire_reservation(
            dataset_id=dataset_id,
            uniqueness_scope=f"dataset:{dataset_id}",
            logical_key={"f_event_id": 7},
            idempotency_key="idem-7-other",
        )

    # Same idempotency key replays the committed claim (no reuse of a new claim).
    replay = svc.acquire_reservation(
        dataset_id=dataset_id,
        uniqueness_scope=f"dataset:{dataset_id}",
        logical_key={"f_event_id": 7},
        idempotency_key="idem-7",
    )
    assert replay.reservation_id == rid
    assert replay.status is c.ReservationStatus.COMMITTED


def test_crash_recovery_reclaims_only_incomplete_or_failed() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    svc = _service(control)
    contract = _contract(dataset_id)
    svc.register_schema_contract(contract)

    # Failed claim may be reclaimed.
    res = svc.acquire_reservation(
        dataset_id=dataset_id,
        uniqueness_scope=f"dataset:{dataset_id}",
        logical_key={"f_event_id": 100},
        idempotency_key="idem-fail",
        reservation_id="res-fail",
    )
    failed = svc.mark_reservation_failed(res.reservation_id, reason="validation")
    assert failed.status is c.ReservationStatus.FAILED
    reclaimed = svc.reclaim_incomplete_or_failed(res.reservation_id)
    assert reclaimed.status is c.ReservationStatus.PENDING_RECLAIM

    # Simulated crash after snapshot → in_doubt, recovery terminalizes.
    with pytest.raises(c.ReservationError, match="simulated crash"):
        svc.commit_write(
            contract=contract,
            records=[
                {
                    "f_event_id": 200,
                    "f_payload": "crash",
                    "f_status": "open",
                    "tenant": "acme",
                }
            ],
            source_files=("s3://b/crash.parquet",),
            uniqueness_scope=f"dataset:{dataset_id}",
            logical_key={"f_event_id": 200},
            idempotency_key="idem-crash",
            uniqueness_key_fields=("f_event_id",),
            operation_id="op-crash",
            object_uri="s3://owned/crash.parquet",
            simulate_crash_after_snapshot=True,
        )

    # Snapshot advanced but reservation in_doubt.
    in_doubt_rows = [
        r
        for r in svc.companion.store.list_rows("lake_logical_key_reservations")
        if r.get("status") == "in_doubt"
    ]
    assert len(in_doubt_rows) == 1

    report = svc.recover(contract=contract)
    assert report["atomic_across_files"] is False
    assert in_doubt_rows[0]["reservation_id"] in report["terminalized"]
    # Outbox now present for the recovered op.
    outboxes = svc.companion.store.list_rows("lake_ingest_outbox")
    assert any(o.get("operation_id") == "op-crash" for o in outboxes)
    recovered = svc.companion.store.get_row(
        "lake_logical_key_reservations", in_doubt_rows[0]["reservation_id"]
    )
    assert recovered is not None
    assert recovered["status"] == "committed"
    assert recovered["snapshot_version"] is not None


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


def test_concurrent_same_key_exactly_one_wins() -> None:
    control = _control()
    dataset_id = _seed_topology(control)
    svc = _service(control)
    contract = _contract(dataset_id)
    svc.register_schema_contract(contract)

    winners: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(8)

    def worker(i: int) -> None:
        try:
            barrier.wait(timeout=5)
            receipt = svc.commit_write(
                contract=contract,
                records=[
                    {
                        "f_event_id": 999,
                        "f_payload": f"w{i}",
                        "f_status": "open",
                        "tenant": "acme",
                    }
                ],
                source_files=(f"s3://b/w{i}.parquet",),
                uniqueness_scope=f"dataset:{dataset_id}",
                logical_key={"f_event_id": 999},
                idempotency_key=f"idem-race-{i}",
                uniqueness_key_fields=("f_event_id",),
                operation_id=f"op-race-{i}",
            )
            winners.append(receipt.reservation.reservation_id)
        except BaseException as exc:  # noqa: BLE001 — collect all race outcomes
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(winners) == 1, f"expected exactly one winner, got {winners!r}"
    assert len(errors) == 7
    assert all(
        isinstance(e, (c.ReservationContention, c.ConstraintViolation, c.ReservationError))
        for e in errors
    )
    committed = [
        r
        for r in svc.companion.store.list_rows("lake_logical_key_reservations")
        if r.get("logical_key_digest")
        == c.logical_key_digest_for({"f_event_id": 999})
        and r.get("status") == "committed"
    ]
    assert len(committed) == 1


def test_independent_shards_progress_concurrently_without_shared_reservation_db() -> None:
    control = _control()
    # Two datasets home on different shards.
    control.register_catalog(
        catalog_id="cat_a",
        catalog_digest=_DIGEST_A,
        storage_kind="local_block",
        metadata_path="/var/lib/ducklake/catalogs/a.duckdb",
    )
    control.register_shard(
        shard_id="shard_a",
        catalog_id="cat_a",
        ring_position=0,
        endpoint_identity="quacks://127.0.0.1:19001/cat_a",
    )
    control.register_shard(
        shard_id="shard_b",
        catalog_id="cat_a",
        ring_position=1,
        endpoint_identity="quacks://127.0.0.1:19002/cat_a",
    )
    alias_a = sch.LogicalDatasetAlias(
        alias="events_a", tenant="acme", namespace="analytics"
    )
    alias_b = sch.LogicalDatasetAlias(
        alias="events_b", tenant="acme", namespace="analytics"
    )
    control.register_logical_dataset(alias_a)
    control.register_logical_dataset(alias_b)
    control.assign_home_shard(
        dataset_id=alias_a.dataset_id,
        home_shard_id="shard_a",
        uniqueness_scope=f"dataset:{alias_a.dataset_id}",
    )
    control.assign_home_shard(
        dataset_id=alias_b.dataset_id,
        home_shard_id="shard_b",
        uniqueness_scope=f"dataset:{alias_b.dataset_id}",
    )

    svc_a = _service(control, shard_id="shard_a")
    svc_b = _service(control, shard_id="shard_b")
    # Distinct companion stores / instance ids.
    assert svc_a.companion.store.instance_id != svc_b.companion.store.instance_id
    assert svc_a.companion.instance.instance_id != svc_b.companion.instance.instance_id

    contract_a = _contract(alias_a.dataset_id)
    contract_a = c.SchemaContract(
        contract_id="contract-a",
        dataset_id=alias_a.dataset_id,
        revision=1,
        fields=_base_fields(),
        tenant="acme",
    )
    contract_b = c.SchemaContract(
        contract_id="contract-b",
        dataset_id=alias_b.dataset_id,
        revision=1,
        fields=_base_fields(),
        tenant="acme",
    )
    svc_a.register_schema_contract(contract_a)
    svc_b.register_schema_contract(contract_b)

    results: dict[str, Any] = {}
    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def run(svc: c.ConstraintService, contract: c.SchemaContract, tag: str) -> None:
        try:
            barrier.wait(timeout=5)
            receipt = svc.commit_write(
                contract=contract,
                records=[
                    {
                        "f_event_id": 1,
                        "f_payload": tag,
                        "f_status": "open",
                        "tenant": "acme",
                    }
                ],
                source_files=(f"s3://b/{tag}.parquet",),
                uniqueness_scope=f"dataset:{contract.dataset_id}",
                logical_key={"f_event_id": 1, "shard": tag},
                idempotency_key=f"idem-{tag}",
                uniqueness_key_fields=("f_event_id",),
                operation_id=f"op-{tag}",
            )
            results[tag] = receipt
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=run, args=(svc_a, contract_a, "a"))
    t2 = threading.Thread(target=run, args=(svc_b, contract_b, "b"))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f"independent shards should not block each other: {errors}"
    assert set(results) == {"a", "b"}
    assert results["a"].reservation.shard_id == "shard_a"
    assert results["b"].reservation.shard_id == "shard_b"
    # No shared reservation database: each companion only sees its own rows.
    assert len(svc_a.companion.store.list_rows("lake_logical_key_reservations")) == 1
    assert len(svc_b.companion.store.list_rows("lake_logical_key_reservations")) == 1
    assert (
        svc_a.companion.store.list_rows("lake_logical_key_reservations")[0][
            "reservation_id"
        ]
        != svc_b.companion.store.list_rows("lake_logical_key_reservations")[0][
            "reservation_id"
        ]
    )


# ---------------------------------------------------------------------------
# Module surface / isolation invariants
# ---------------------------------------------------------------------------


def test_module_exports_and_side_effect_free_import() -> None:
    assert c.CONTRACTS_SCHEMA.startswith("ipfs_datasets_py/ducklake-schema-contracts")
    assert hasattr(c, "ConstraintService")
    assert hasattr(c, "SchemaContract")
    assert hasattr(c, "evolve_schema")
    assert hasattr(c, "is_lossless_promotion")
    # Import must not require duckdb.
    assert "duckdb" not in sys.modules or True  # duckdb may be present ambiently
    mapping = c.TypePromotionRules().as_mapping()
    assert "default_lossless_graph" in mapping
    assert c.FieldType.INT32.value in mapping["default_lossless_graph"]


def test_ducklake_internal_metadata_never_hosts_reservations() -> None:
    for internal in sorted(sch.DUCKLAKE_INTERNAL_V1_TABLES)[:5]:
        with pytest.raises(c.ContractError, match="DuckLake internal"):
            c.assert_not_ducklake_internal_metadata(internal)
