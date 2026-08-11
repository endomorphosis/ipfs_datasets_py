"""Integration tests for transactional Parquet ingest + ownership transfer (DQK-088).

Covers acceptance criteria:

* Lost responses and retries create one logical snapshot
* Source files and source CIDs remain untouched; DuckLake receives a
  lifecycle-managed owned copy
* Ownership-transfer authorization is non-self-issued and binds caller/process
  birth, generation fence, catalog, DATA_PATH, source identity, destination
  object version/digest, lifecycle policy, operation, nonce, and expiry
* Each privileged copy, registration, and ownership-transfer call is
  independently authorized and revalidated at use; one receipt cannot confer
  ambient future delete authority
* Staging files cannot be mistaken for orphans under DATA_PATH
* Partial object upload, catalog commit, or receipt publication is reconciled
  or quarantined
* Missing/extra columns and type promotion follow the validated DQK-094 schema
  policy rather than permissive defaults

Hermetic: real local filesystem copies + DQK-086 memory registries (no live
DuckDB/network required).
"""

from __future__ import annotations

import hashlib
import sys
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

from ipfs_datasets_py.ducklake import admission as adm
from ipfs_datasets_py.ducklake import contracts as c
from ipfs_datasets_py.ducklake import ingest as ing
from ipfs_datasets_py.ducklake import registry as reg
from ipfs_datasets_py.ducklake import schema as sch
from ipfs_datasets_py.ducklake.config import (
    ParquetNamespace,
    ParquetStorageKind,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_DIGEST_A = "sha256:" + ("ab" * 32)
_FIELDS = (
    {"name": "event_id", "type": "int64"},
    {"name": "payload", "type": "utf8"},
    {"name": "amount", "type": "float64"},
    {"name": "status", "type": "utf8"},
)


def _control() -> reg.ControlLakeRegistry:
    control = reg.ControlLakeRegistry(owner_id="control-dqk088")
    control.apply_migrations()
    return control


def _seed_topology(control: reg.ControlLakeRegistry) -> str:
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


def _namespace(tmp_path: Path, *, catalog_id: str = "cat_a") -> ParquetNamespace:
    data = tmp_path / "lake" / "data" / catalog_id
    staging = tmp_path / "lake" / "staging" / catalog_id
    data.mkdir(parents=True, exist_ok=True)
    staging.mkdir(parents=True, exist_ok=True)
    return ParquetNamespace(
        data_path=str(data.resolve()),
        staging_path=str(staging.resolve()),
        storage_kind=ParquetStorageKind.LOCAL,
        namespace_id=f"{catalog_id}_ns",
        allowlist=(str(tmp_path.resolve()),),
        provenance_cid_roots=("bafybeigdyrztcidprov",),
    )


def _process_birth() -> ing.ProcessBirth:
    return ing.default_process_birth(
        process_id="worker-proc-1",
        boot_id="boot-1",
        hostname="test-host",
        pid=4242,
    )


def _contract(dataset_id: str, *, column_policy: c.ColumnPolicy | None = None) -> c.SchemaContract:
    return c.SchemaContract(
        contract_id="contract-events-v1",
        dataset_id=dataset_id,
        revision=1,
        fields=(
            c.FieldContract(
                field_id="f_event_id",
                name="event_id",
                field_type=c.FieldType.INT64,
                nullable=False,
                required=True,
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
                field_type=c.FieldType.FLOAT64,
                nullable=True,
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
        ),
        tenant="acme",
        column_policy=column_policy
        or c.ColumnPolicy(
            missing=c.MissingColumnPolicy.REJECT,
            extra=c.ExtraColumnPolicy.REJECT,
        ),
        uniqueness_scopes=(f"dataset:{dataset_id}",),
    )


def _write_source(path: Path, *, rows: list[dict[str, Any]] | None = None) -> Path:
    return adm.write_admission_parquet(
        path,
        fields=_FIELDS,
        rows=rows
        or [
            {
                "event_id": 1,
                "payload": "alpha",
                "amount": 1.5,
                "status": "open",
            },
            {
                "event_id": 2,
                "payload": "beta",
                "amount": 2.5,
                "status": "closed",
            },
        ],
        partition_hints={"dt": "2026-08-10"},
    )


def _service(
    tmp_path: Path,
    control: reg.ControlLakeRegistry,
    *,
    generation_fence: int = 7,
    caller_id: str = "ingest-worker-1",
    broker_id: str = "owner-broker-1",
) -> tuple[ing.IngestService, ParquetNamespace, str]:
    dataset_id = _seed_topology(control)
    ns = _namespace(tmp_path)
    birth = _process_birth()
    broker = ing.OwnerBroker(
        broker_id=broker_id,
        catalog_id="cat_a",
        data_path=ns.data_path,
        generation_fence=generation_fence,
    )
    companion = reg.CompanionLakeRegistry(
        shard_id="shard_a",
        owner_id="owner-shard-a",
        control=control,
    )
    companion.apply_migrations()
    constraints = c.ConstraintService(
        shard_id="shard_a",
        owner_id="owner-shard-a",
        control=control,
        companion=companion,
        catalog_id="cat_a",
    )
    constraints.register_schema_contract(_contract(dataset_id))
    svc = ing.IngestService(
        shard_id="shard_a",
        owner_id="owner-shard-a",
        catalog_id="cat_a",
        parquet_namespace=ns,
        broker=broker,
        control=control,
        companion=companion,
        constraint_service=constraints,
        caller_id=caller_id,
        process_birth=birth,
        generation_fence=generation_fence,
        lifecycle_policy=ing.LifecyclePolicy(
            policy_id="lifecycle-cat_a",
            retention_class="standard",
            replace_allowed=True,
            delete_allowed=True,
        ),
    )
    return svc, ns, dataset_id


def _records() -> list[dict[str, Any]]:
    return [
        {
            "f_event_id": 1,
            "f_payload": "alpha",
            "f_amount": 1.5,
            "f_status": "open",
            "tenant": "acme",
        },
        {
            "f_event_id": 2,
            "f_payload": "beta",
            "f_amount": 2.5,
            "f_status": "closed",
            "tenant": "acme",
        },
    ]


# ---------------------------------------------------------------------------
# Happy path: owned copy + registration
# ---------------------------------------------------------------------------


def test_ingest_creates_lifecycle_managed_owned_copy_and_registers(
    tmp_path: Path,
) -> None:
    control = _control()
    svc, ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "events" / "part-000.parquet")
    source_bytes = source.read_bytes()
    source_digest = "sha256:" + hashlib.sha256(source_bytes).hexdigest()

    receipt = svc.ingest(
        source_path=source,
        dataset_id=dataset_id,
        idempotency_key="idem-happy-1",
        schema_contract=_contract(dataset_id),
        records=_records(),
        operation_id="op-happy-1",
    )

    assert receipt.committed is True
    assert receipt.phase is ing.IngestPhase.COMMITTED
    assert receipt.snapshot_version == 1
    assert receipt.source_untouched is True
    assert receipt.atomic_across_files is False
    assert receipt.source.content_digest == source_digest
    assert receipt.destination is not None
    assert receipt.destination.content_digest == source_digest
    assert receipt.registration is not None
    assert receipt.registration.function == ing.DUCKLAKE_ADD_DATA_FILES
    assert receipt.registration.snapshot_version == 1

    # Source untouched.
    assert source.read_bytes() == source_bytes
    assert source.exists()

    # Owned copy under DATA_PATH, distinct from source.
    owned = Path(receipt.destination.owned_uri)
    assert owned.is_file()
    assert owned.read_bytes() == source_bytes
    assert str(owned).startswith(ns.data_path.rstrip("/"))
    assert owned.resolve() != source.resolve()

    # Staging was outside DATA_PATH (and cleaned after success).
    if receipt.staged is not None:
        staged = Path(receipt.staged.staging_uri)
        assert not str(staged).startswith(ns.data_path.rstrip("/") + "/")
        # cleanup may have removed it
        if staged.exists():
            assert not str(staged.resolve()).startswith(
                str(Path(ns.data_path).resolve()) + "/"
            )

    # Catalog registered the owned URI only.
    assert receipt.destination.owned_uri in svc.catalog.registered_files
    assert source.as_uri() not in svc.catalog.registered_files


# ---------------------------------------------------------------------------
# Idempotency: lost responses / retries → one logical snapshot
# ---------------------------------------------------------------------------


def test_lost_response_and_retry_create_one_logical_snapshot(tmp_path: Path) -> None:
    control = _control()
    svc, _ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")
    contract = _contract(dataset_id)

    first = svc.ingest(
        source_path=source,
        dataset_id=dataset_id,
        idempotency_key="idem-retry-1",
        schema_contract=contract,
        records=_records(),
        operation_id="op-retry-1",
    )
    # Lost response: client retries with same idempotency key (new or same op id).
    second = svc.ingest(
        source_path=source,
        dataset_id=dataset_id,
        idempotency_key="idem-retry-1",
        schema_contract=contract,
        records=_records(),
        operation_id="op-retry-1-retry",
    )
    third = svc.ingest(
        source_path=source,
        dataset_id=dataset_id,
        idempotency_key="idem-retry-1",
        schema_contract=contract,
        records=_records(),
        operation_id="op-retry-1",
    )

    assert first.committed and second.committed and third.committed
    assert first.snapshot_version == second.snapshot_version == third.snapshot_version
    assert first.receipt_digest() == second.receipt_digest() == third.receipt_digest()
    # Catalog advanced only once.
    assert svc.catalog.snapshot_version == 1
    assert len(svc.catalog.registered_files) == 1


# ---------------------------------------------------------------------------
# Ownership-transfer authorization bindings
# ---------------------------------------------------------------------------


def test_ownership_transfer_is_non_self_issued_and_fully_bound(
    tmp_path: Path,
) -> None:
    control = _control()
    svc, ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")
    _, digest = adm.stream_file_digest(source)
    birth = svc.process_birth
    source_id = ing.SourceIdentity(
        source_uri=source.resolve().as_uri(),
        content_digest=digest,
        ownership_kind=adm.SourceOwnershipKind.EXTERNAL_UNMANAGED,
        byte_size=source.stat().st_size,
    )
    dest = ing.DestinationObjectIdentity(
        owned_uri=str(Path(ns.data_path) / "owned" / "x.parquet"),
        content_digest=digest,
        object_version=1,
        namespace_id=ns.namespace_id,
    )

    # Self-issued fails closed.
    with pytest.raises(ing.OwnershipTransferError, match="non-self-issued"):
        ing.OwnershipTransferAuthorization(
            authorization_id="bad",
            operation_id="op-1",
            caller_id="same-id",
            process_birth=birth,
            generation_fence=7,
            catalog_id="cat_a",
            data_path=ns.data_path,
            source=source_id,
            destination=dest,
            lifecycle_policy=svc.lifecycle_policy,
            issuer_id="same-id",
            nonce="n1",
            expires_at_unix=9_999_999_999,
        )

    auth = svc.broker.issue_ownership_transfer(
        operation_id="op-bind-1",
        caller_id=svc.caller_id,
        process_birth=birth,
        generation_fence=svc.generation_fence,
        source=source_id,
        destination=dest,
        lifecycle_policy=svc.lifecycle_policy,
    )
    mapping = auth.as_mapping()
    assert mapping["non_self_issued"] is True
    assert mapping["issuer_id"] == "owner-broker-1"
    assert mapping["issuer_id"] != mapping["caller_id"]
    assert mapping["operation"] == "ownership_transfer"
    assert mapping["operation_id"] == "op-bind-1"
    assert mapping["generation_fence"] == 7
    assert mapping["catalog_id"] == "cat_a"
    assert mapping["data_path"] == ns.data_path
    assert mapping["source"]["content_digest"] == digest
    assert mapping["destination"]["object_version"] == 1
    assert mapping["destination"]["content_digest"] == digest
    assert mapping["lifecycle_policy"]["policy_id"] == "lifecycle-cat_a"
    assert mapping["replace_allowed"] is True
    assert mapping["delete_allowed"] is True
    assert mapping["confers_ambient_delete"] is False
    assert mapping["nonce"]
    assert mapping["expires_at_unix"] > 0
    assert mapping["process_birth"]["fingerprint"] == birth.fingerprint()
    assert mapping["binding_digest"].startswith("sha256:")

    # Revalidation with wrong fence fails.
    with pytest.raises(ing.OwnershipTransferError, match="generation_fence"):
        ing.revalidate_ownership_transfer_authorization(
            auth,
            operation_id="op-bind-1",
            caller_id=svc.caller_id,
            process_birth=birth,
            generation_fence=999,
            catalog_id="cat_a",
            data_path=ns.data_path,
            source=source_id,
            destination=dest,
            lifecycle_policy=svc.lifecycle_policy,
        )

    # Successful revalidate marks used; second use fails (no ambient authority).
    used = ing.revalidate_ownership_transfer_authorization(
        auth,
        operation_id="op-bind-1",
        caller_id=svc.caller_id,
        process_birth=birth,
        generation_fence=7,
        catalog_id="cat_a",
        data_path=ns.data_path,
        source=source_id,
        destination=dest,
        lifecycle_policy=svc.lifecycle_policy,
    )
    assert used.used is True
    with pytest.raises(ing.OwnershipTransferError, match="already consumed"):
        ing.revalidate_ownership_transfer_authorization(
            used,
            operation_id="op-bind-1",
            caller_id=svc.caller_id,
            process_birth=birth,
            generation_fence=7,
            catalog_id="cat_a",
            data_path=ns.data_path,
            source=source_id,
            destination=dest,
            lifecycle_policy=svc.lifecycle_policy,
        )


def test_each_privileged_call_independently_authorized_no_ambient_delete(
    tmp_path: Path,
) -> None:
    control = _control()
    svc, ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")
    receipt = svc.ingest(
        source_path=source,
        dataset_id=dataset_id,
        idempotency_key="idem-auth-1",
        schema_contract=_contract(dataset_id),
        records=_records(),
        operation_id="op-auth-1",
    )
    assert receipt.copy_authorization_id
    assert receipt.register_authorization_id
    assert receipt.ownership_transfer_authorization_id
    # All three distinct.
    assert len(
        {
            receipt.copy_authorization_id,
            receipt.register_authorization_id,
            receipt.ownership_transfer_authorization_id,
        }
    ) == 3
    # Transfer does not authorize delete.
    assert svc.broker.was_consumed(receipt.ownership_transfer_authorization_id)
    delete_auth = svc.authorize_delete_independently(
        operation_id="op-delete-1",
        subject_digest=receipt.destination.content_digest,  # type: ignore[union-attr]
    )
    assert delete_auth.kind is ing.AuthorizationKind.DELETE
    assert delete_auth.authorization_id != receipt.ownership_transfer_authorization_id
    assert delete_auth.issuer_id != delete_auth.caller_id

    # Using transfer receipt as a delete authorization is impossible by kind.
    with pytest.raises(ing.AuthorizationError):
        # Build a fake attempt: revalidate transfer binding as COPY kind fails
        # because kinds are independent and transfer is already consumed.
        copy_auth = svc.broker.issue_privileged_authorization(
            kind=ing.AuthorizationKind.COPY,
            operation_id="op-other",
            caller_id=svc.caller_id,
            process_birth=svc.process_birth,
            generation_fence=svc.generation_fence,
            subject_digest=receipt.source.content_digest,
        )
        # Wrong kind revalidation.
        ing.revalidate_privileged_authorization(
            copy_auth,
            kind=ing.AuthorizationKind.DELETE,
            operation_id="op-other",
            caller_id=svc.caller_id,
            process_birth=svc.process_birth,
            generation_fence=svc.generation_fence,
            catalog_id="cat_a",
            data_path=ns.data_path,
            subject_digest=receipt.source.content_digest,
        )


def test_self_issued_privileged_authorization_rejected(tmp_path: Path) -> None:
    ns = _namespace(tmp_path)
    birth = _process_birth()
    with pytest.raises(ing.AuthorizationError, match="non-self-issued"):
        ing.PrivilegedCallAuthorization(
            authorization_id="a1",
            kind=ing.AuthorizationKind.COPY,
            operation_id="op",
            caller_id="worker",
            process_birth=birth,
            generation_fence=1,
            catalog_id="cat_a",
            data_path=ns.data_path,
            issuer_id="worker",
            nonce="n",
            expires_at_unix=9_999_999_999,
            subject_digest="sha256:" + ("11" * 32),
        )


# ---------------------------------------------------------------------------
# Staging outside DATA_PATH
# ---------------------------------------------------------------------------


def test_staging_cannot_live_under_data_path(tmp_path: Path) -> None:
    data = tmp_path / "data"
    data.mkdir()
    with pytest.raises(ing.StagingError, match="outside DATA_PATH"):
        ing.assert_staging_outside_data_path(
            data / "staging", data, storage_kind=ParquetStorageKind.LOCAL
        )

    with pytest.raises(Exception, match="outside DATA_PATH"):
        ParquetNamespace(
            data_path=str(data.resolve()),
            staging_path=str((data / "staging").resolve()),
            storage_kind=ParquetStorageKind.LOCAL,
            namespace_id="bad_ns",
            allowlist=(str(tmp_path.resolve()),),
        )


def test_ingest_stages_outside_data_path_and_registers_only_owned(
    tmp_path: Path,
) -> None:
    control = _control()
    svc, ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")

    # Crash after stage to inspect staging placement.
    with pytest.raises(ing.QuarantineError, match="partial stage"):
        svc.ingest(
            source_path=source,
            dataset_id=dataset_id,
            idempotency_key="idem-stage-1",
            schema_contract=_contract(dataset_id),
            records=_records(),
            operation_id="op-stage-1",
            simulate_crash_after="stage",
        )
    flight = svc._in_flight["op-stage-1"]
    staged_uri = flight["staged"]["staging_uri"]
    assert not staged_uri.startswith(ns.data_path.rstrip("/") + "/")
    assert Path(staged_uri).is_file()
    # Content-bound key includes digest path.
    assert "content" in staged_uri
    # Not registered yet.
    assert svc.catalog.snapshot_version == 0
    assert not svc.catalog.registered_files


# ---------------------------------------------------------------------------
# Partial failure: reconcile or quarantine
# ---------------------------------------------------------------------------


def test_partial_catalog_commit_is_reconciled_to_one_snapshot(
    tmp_path: Path,
) -> None:
    control = _control()
    svc, _ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")
    contract = _contract(dataset_id)

    with pytest.raises(ing.QuarantineError, match="partial"):
        svc.ingest(
            source_path=source,
            dataset_id=dataset_id,
            idempotency_key="idem-crash-reg",
            schema_contract=contract,
            records=_records(),
            operation_id="op-crash-reg",
            simulate_crash_after="register",
        )
    # Snapshot advanced but receipt not published.
    assert svc.catalog.snapshot_version >= 1
    prior = svc.get_receipt("op-crash-reg")
    assert prior is not None
    assert prior.phase is ing.IngestPhase.QUARANTINED

    recovered = svc.reconcile(operation_id="op-crash-reg")
    assert isinstance(recovered, ing.IngestReceipt)
    assert recovered.committed is True
    assert recovered.snapshot_version == svc.catalog.snapshot_version

    # Retry does not create a second snapshot.
    again = svc.ingest(
        source_path=source,
        dataset_id=dataset_id,
        idempotency_key="idem-crash-reg",
        schema_contract=contract,
        records=_records(),
        operation_id="op-crash-reg-retry",
    )
    assert again.snapshot_version == recovered.snapshot_version
    assert svc.catalog.snapshot_version == recovered.snapshot_version


def test_partial_stage_without_catalog_remains_quarantined(tmp_path: Path) -> None:
    control = _control()
    svc, _ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")

    with pytest.raises(ing.QuarantineError):
        svc.ingest(
            source_path=source,
            dataset_id=dataset_id,
            idempotency_key="idem-q-stage",
            schema_contract=_contract(dataset_id),
            records=_records(),
            operation_id="op-q-stage",
            simulate_crash_after="stage",
        )
    with pytest.raises(ing.QuarantineError, match="quarantined"):
        svc.reconcile(operation_id="op-q-stage")
    assert svc.catalog.snapshot_version == 0


# ---------------------------------------------------------------------------
# External / CID sources never registered live
# ---------------------------------------------------------------------------


def test_never_register_external_or_immutable_cid_as_live_data_path(
    tmp_path: Path,
) -> None:
    control = _control()
    svc, ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")
    source_bytes = source.read_bytes()

    receipt = svc.ingest(
        source_path=source,
        dataset_id=dataset_id,
        idempotency_key="idem-ext-1",
        schema_contract=_contract(dataset_id),
        records=_records(),
        operation_id="op-ext-1",
        source_ownership_kind=adm.SourceOwnershipKind.EXTERNAL_UNMANAGED,
    )
    assert receipt.source.ownership_kind is adm.SourceOwnershipKind.EXTERNAL_UNMANAGED
    assert receipt.source.is_external_or_immutable_cid is True
    assert receipt.destination is not None
    assert receipt.destination.owned_uri != receipt.source.source_uri
    assert Path(receipt.destination.owned_uri).read_bytes() == source_bytes
    # Catalog only knows the owned path.
    assert set(svc.catalog.registered_files.keys()) == {receipt.destination.owned_uri}

    # Explicit CID destination is rejected by DestinationObjectIdentity.
    with pytest.raises(ing.ExternalSourceRegistrationError, match="CID"):
        ing.DestinationObjectIdentity(
            owned_uri="ipfs://bafybeigdyrztcidonly",
            content_digest=receipt.source.content_digest,
            object_version=1,
        )

    # ducklake_add_data_files refuses CID URIs.
    with pytest.raises(ing.ExternalSourceRegistrationError):
        svc.catalog.add_data_files(
            operation_id="op-bad-cid",
            owned_uri="ipfs://bafybeigdyrztcidonly",
            content_digest=receipt.source.content_digest,
            ownership_transfer_authorization_id="x",
            register_authorization_id="y",
        )

    # Lifecycle policy forbidding external register is the only allowed default.
    with pytest.raises(ing.IngestError, match="external register"):
        ing.LifecyclePolicy(
            policy_id="bad",
            allow_external_register=True,
        )


# ---------------------------------------------------------------------------
# DQK-094 schema policy (missing/extra + type promotion)
# ---------------------------------------------------------------------------


def test_missing_extra_columns_follow_dqk094_policy_not_permissive_defaults(
    tmp_path: Path,
) -> None:
    control = _control()
    svc, _ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")
    contract = _contract(dataset_id)  # REJECT missing/extra

    # Extra column rejected.
    with pytest.raises(ing.IngestError, match="column policy|extra"):
        svc.ingest(
            source_path=source,
            dataset_id=dataset_id,
            idempotency_key="idem-extra",
            schema_contract=contract,
            records=[
                {
                    "f_event_id": 1,
                    "f_payload": "x",
                    "f_status": "open",
                    "f_unknown": "nope",
                    "tenant": "acme",
                }
            ],
            operation_id="op-extra",
        )

    # Missing required column rejected.
    with pytest.raises(ing.IngestError, match="column policy|missing|rejected"):
        svc.ingest(
            source_path=source,
            dataset_id=dataset_id,
            idempotency_key="idem-missing",
            schema_contract=contract,
            records=[
                {
                    "f_event_id": 1,
                    "f_payload": "x",
                    # f_status missing
                    "tenant": "acme",
                }
            ],
            operation_id="op-missing",
        )

    # Explicit DROP extra policy allows extra columns to be dropped.
    drop_contract = _contract(
        dataset_id,
        column_policy=c.ColumnPolicy(
            missing=c.MissingColumnPolicy.REJECT,
            extra=c.ExtraColumnPolicy.DROP,
        ),
    )
    # Need a fresh service / reservation key space — reuse service with new key.
    receipt = svc.ingest(
        source_path=source,
        dataset_id=dataset_id,
        idempotency_key="idem-drop-extra",
        schema_contract=drop_contract,
        records=[
            {
                "f_event_id": 10,
                "f_payload": "ok",
                "f_status": "open",
                "f_unknown": "dropped",
                "tenant": "acme",
            }
        ],
        operation_id="op-drop-extra",
    )
    assert receipt.committed is True


def test_lossy_type_promotion_rejected_under_dqk094_rules(tmp_path: Path) -> None:
    control = _control()
    svc, _ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")
    contract = _contract(dataset_id)

    with pytest.raises(ing.IngestError, match="type promotion|promotion"):
        svc.ingest(
            source_path=source,
            dataset_id=dataset_id,
            idempotency_key="idem-lossy",
            schema_contract=contract,
            records=[
                {
                    "f_event_id": 1_000_000_000_000,
                    "f_payload": "x",
                    "f_status": "open",
                    "tenant": "acme",
                    "__types__": {"f_event_id": "float64"},  # float64 -> int64 lossy
                }
            ],
            operation_id="op-lossy",
        )


def test_lossless_type_promotion_accepted(tmp_path: Path) -> None:
    control = _control()
    svc, _ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")
    contract = _contract(dataset_id)

    receipt = svc.ingest(
        source_path=source,
        dataset_id=dataset_id,
        idempotency_key="idem-lossless",
        schema_contract=contract,
        records=[
            {
                "f_event_id": 7,
                "f_payload": "x",
                "f_status": "open",
                "tenant": "acme",
                "__types__": {"f_event_id": "int32"},  # int32 -> int64 lossless
            }
        ],
        operation_id="op-lossless",
    )
    assert receipt.committed is True


# ---------------------------------------------------------------------------
# Content-bound object keys + source CID provenance
# ---------------------------------------------------------------------------


def test_content_bound_object_key_is_deterministic() -> None:
    digest = "sha256:" + ("cd" * 32)
    k1 = ing.content_bound_object_key(
        content_digest=digest, dataset_id="events", object_version=1
    )
    k2 = ing.content_bound_object_key(
        content_digest=digest, dataset_id="events", object_version=1
    )
    assert k1 == k2
    assert "events/v1/" in k1
    assert digest[len("sha256:") :] in k1


def test_admission_receipt_path_preserves_source_cid_as_provenance(
    tmp_path: Path,
) -> None:
    control = _control()
    svc, _ns, dataset_id = _service(tmp_path, control)
    source = _write_source(tmp_path / "sources" / "part-000.parquet")
    admission = adm.AdmissionService(
        owner_id="owner-shard-a",
        shard_id="shard_a",
        allowed_roots=(tmp_path / "sources",),
    )
    adm_receipt = admission.admit(
        source,
        provenance=adm.Provenance(
            producer="test",
            tenant="acme",
            dataset_alias="events",
            namespace="analytics",
        ),
        content_cid="bafybeigdyrztcidprovenanceonly",
        dataset_id=dataset_id,
        ownership_kind=adm.SourceOwnershipKind.EXTERNAL_UNMANAGED,
    )
    assert adm_receipt.admitted
    assert adm_receipt.copy_required is True

    receipt = svc.ingest(
        source_path=source,
        dataset_id=dataset_id,
        idempotency_key="idem-adm-1",
        schema_contract=_contract(dataset_id),
        records=_records(),
        admission_receipt=adm_receipt,
        operation_id="op-adm-1",
    )
    assert receipt.source.content_cid == "bafybeigdyrztcidprovenanceonly"
    assert receipt.destination is not None
    assert not receipt.destination.owned_uri.startswith("ipfs://")
    # Source still present and unchanged.
    assert source.exists()
    assert receipt.source_untouched is True


# ---------------------------------------------------------------------------
# Broker / worker identity separation
# ---------------------------------------------------------------------------


def test_ingest_caller_cannot_be_broker_identity(tmp_path: Path) -> None:
    control = _control()
    ns = _namespace(tmp_path)
    with pytest.raises(ing.IngestError, match="differ from trusted owner broker"):
        ing.IngestService(
            shard_id="shard_a",
            owner_id="owner",
            catalog_id="cat_a",
            parquet_namespace=ns,
            broker=ing.OwnerBroker(
                broker_id="same",
                catalog_id="cat_a",
                data_path=ns.data_path,
                generation_fence=1,
            ),
            control=control,
            caller_id="same",
            process_birth=_process_birth(),
            generation_fence=1,
        )


def test_expired_authorization_fails_revalidation(tmp_path: Path) -> None:
    ns = _namespace(tmp_path)
    birth = _process_birth()
    broker = ing.OwnerBroker(
        broker_id="broker",
        catalog_id="cat_a",
        data_path=ns.data_path,
        generation_fence=1,
        clock=lambda: 1_000.0,
    )
    auth = broker.issue_privileged_authorization(
        kind=ing.AuthorizationKind.COPY,
        operation_id="op",
        caller_id="worker",
        process_birth=birth,
        generation_fence=1,
        subject_digest="sha256:" + ("22" * 32),
        ttl_seconds=10,
    )
    with pytest.raises(ing.AuthorizationError, match="expired"):
        ing.revalidate_privileged_authorization(
            auth,
            kind=ing.AuthorizationKind.COPY,
            operation_id="op",
            caller_id="worker",
            process_birth=birth,
            generation_fence=1,
            catalog_id="cat_a",
            data_path=ns.data_path,
            subject_digest="sha256:" + ("22" * 32),
            now=2_000.0,
        )
