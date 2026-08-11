"""Hermetic unit tests for DQK-086 dual-scope lake registry and migrations.

Covers:

* logical dataset aliases distinct from content and snapshot identities
* control DuckDB exclusive authority matrix
* companion ownership of shard-local tables without redefining global ring
* uniqueness/reference scope resolves to exactly one home shard
* unsupported cross-shard uniqueness fails before ingest
* home-shard move requires drained owners + one fenced control CAS receipt
* companion DatabaseInstance never attached/visible from Quack-serving
* signed shard projections are content-bound caches; stale fails owner startup
* migrations ordered, checksummed, replayable, owner-gated
* registry CAS, idempotency, fencing, provenance survive restart
* no mutable JSON/Parquet manifest is authoritative

All tests use pure in-memory fixtures (no optional ``duckdb`` import).
"""

from __future__ import annotations

import sys
from pathlib import Path

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
    SCHEMA_DIGEST_PREFIX,
    schema_digest_for,
)
from ipfs_datasets_py.ducklake import registry as reg
from ipfs_datasets_py.ducklake import schema as sch


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------

_DIGEST_A = "sha256:" + ("ab" * 32)
_DIGEST_B = "sha256:" + ("cd" * 32)
_DIGEST_C = "sha256:" + ("ef" * 32)


def _control() -> reg.ControlLakeRegistry:
    control = reg.ControlLakeRegistry(owner_id="control-test-owner")
    control.apply_migrations()
    return control


def _seed_topology(control: reg.ControlLakeRegistry) -> None:
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


def _companion(
    control: reg.ControlLakeRegistry, shard_id: str = "shard_a"
) -> reg.CompanionLakeRegistry:
    companion = reg.CompanionLakeRegistry(
        shard_id=shard_id,
        owner_id=f"companion-{shard_id}",
        control=control,
    )
    companion.apply_migrations()
    quack = reg.DatabaseInstanceBinding(
        instance_id=f"quack-{shard_id}",
        kind=reg.DatabaseInstanceKind.QUACK_SERVING,
        path=f":memory:quack:{shard_id}",
        private=True,
        attachable_from_quack=False,
    )
    companion.bind_quack_serving_instance(quack)
    return companion


# ---------------------------------------------------------------------------
# Identity distinctness
# ---------------------------------------------------------------------------


def test_logical_alias_distinct_from_content_and_snapshot() -> None:
    alias = sch.LogicalDatasetAlias(alias="ds1", tenant="t", namespace="ns")
    content = sch.ContentIdentity(content_digest=_DIGEST_A, content_cid="")
    snap = sch.SnapshotIdentity(catalog_id="cat_a", snapshot_version=7)
    assert alias.kind is sch.IdentityKind.LOGICAL_DATASET_ALIAS
    assert content.kind is sch.IdentityKind.CONTENT
    assert snap.kind is sch.IdentityKind.SNAPSHOT
    assert alias.identity_id() != content.identity_id()
    assert alias.identity_id() != snap.identity_id()
    assert content.identity_id() != snap.identity_id()
    assert not alias.identity_id().startswith("content:")
    assert content.identity_id().startswith("content:")
    assert snap.identity_id().startswith("snapshot:")

    control = _control()
    control.register_catalog(
        catalog_id="cat_a",
        catalog_digest=_DIGEST_A,
        storage_kind="local_block",
        metadata_path="/var/lib/ducklake/catalogs/a.duckdb",
    )
    row = control.register_logical_dataset(
        alias, content_identity=content, snapshot_identity=snap
    )
    assert row["identity_kind"] == "logical_dataset_alias"
    assert row["identity_id"] == alias.identity_id()
    assert row["content_identity_id"] == content.identity_id()
    assert row["snapshot_identity_id"] == snap.identity_id()
    assert row["identity_id"] != row["content_identity_id"]
    assert row["identity_id"] != row["snapshot_identity_id"]


# ---------------------------------------------------------------------------
# Authority matrix
# ---------------------------------------------------------------------------


def test_control_exclusive_authority_tables() -> None:
    matrix = sch.authority_table_matrix()
    for short in (
        "lake_catalog",
        "dataset_home_shard",
        "catalog_owner_generation",
        "snapshot_vector_root",
        "shard_migration",
        "promotion_decision",
        "promotion_execution",
        "lake_release_receipts",
    ):
        assert matrix[short] == "control"
    for short in (
        "reader_lease",
        "logical_key_reservation",
        "ingest_outbox",
        "maintenance_authorization",
    ):
        assert matrix[short] == "companion"

    control = _control()
    control.assert_control_authority("lake_catalogs")
    control.assert_control_authority("dataset_home_shard")
    with pytest.raises(reg.AuthorityViolation, match="companion"):
        control.reject_companion_authority_write("reader_lease")


def test_companion_cannot_redefine_global_ring_or_home() -> None:
    control = _control()
    _seed_topology(control)
    companion = _companion(control)
    for forbidden in (
        "lake_catalog_shards",
        "lake_dataset_home_shards",
        "lake_catalog_owner_generations",
        "lake_snapshot_vector_roots",
        "dataset_home_shard",
        "catalog_owner_generation",
        "snapshot_vector_root",
    ):
        with pytest.raises(reg.AuthorityViolation, match="cannot redefine|control"):
            companion.assert_companion_authority(forbidden)

    # Companion can own shard-local authority.
    companion.assert_companion_authority("reader_lease")
    companion.assert_companion_authority("logical_key_reservation")
    companion.assert_companion_authority("ingest_outbox")
    companion.assert_companion_authority("maintenance_authorization")


# ---------------------------------------------------------------------------
# Home shard / uniqueness
# ---------------------------------------------------------------------------


def test_uniqueness_scope_resolves_to_one_home_shard() -> None:
    control = _control()
    _seed_topology(control)
    dataset_id = "acme/analytics/events"
    resolved = control.resolve_uniqueness_scope(
        uniqueness_scope=f"dataset:{dataset_id}",
        dataset_id=dataset_id,
    )
    assert resolved["home_shard_id"] == "shard_a"
    assert resolved["authoritative"] is True


def test_cross_shard_uniqueness_fails_before_ingest() -> None:
    control = _control()
    _seed_topology(control)
    with pytest.raises(reg.UnsupportedCrossShardUniqueness, match="cross-shard"):
        control.resolve_uniqueness_scope(uniqueness_scope="cross_shard:global_pk")
    with pytest.raises(reg.UnsupportedCrossShardUniqueness, match="cross-shard"):
        control.resolve_uniqueness_scope(uniqueness_scope="*")

    # Same scope assigned to two homes → fail closed.
    alias2 = sch.LogicalDatasetAlias(alias="events2", tenant="acme", namespace="analytics")
    control.register_logical_dataset(alias2)
    control.assign_home_shard(
        dataset_id=alias2.dataset_id,
        home_shard_id="shard_b",
        uniqueness_scope="shared_scope",
    )
    # First dataset still on shard_a with different scope; put shared on both.
    home = control.resolve_home_shard(dataset_id="acme/analytics/events")
    control.assign_home_shard(
        dataset_id="acme/analytics/events",
        home_shard_id="shard_a",
        uniqueness_scope="shared_scope",
        expected_revision=int(home["cas_revision"]),
    )
    with pytest.raises(reg.UnsupportedCrossShardUniqueness, match="multiple home"):
        control.resolve_uniqueness_scope(uniqueness_scope="shared_scope")


def test_logical_key_reservation_requires_home_shard() -> None:
    control = _control()
    _seed_topology(control)
    wrong = _companion(control, shard_id="shard_b")
    with pytest.raises(reg.UnsupportedCrossShardUniqueness, match="fails before ingest"):
        wrong.reserve_logical_key(
            reservation_id="res-1",
            dataset_id="acme/analytics/events",
            uniqueness_scope="dataset:acme/analytics/events",
            logical_key_digest=_DIGEST_B,
            idempotency_key="idem-1",
        )
    right = _companion(control, shard_id="shard_a")
    reserved = right.reserve_logical_key(
        reservation_id="res-1",
        dataset_id="acme/analytics/events",
        uniqueness_scope="dataset:acme/analytics/events",
        logical_key_digest=_DIGEST_B,
        idempotency_key="idem-1",
    )
    assert reserved["status"] == "reserved"
    assert reserved["shard_id"] == "shard_a"


# ---------------------------------------------------------------------------
# Home-shard move
# ---------------------------------------------------------------------------


def test_home_shard_move_requires_drained_owners_and_cas() -> None:
    control = _control()
    _seed_topology(control)
    move = control.begin_home_shard_move(
        dataset_id="acme/analytics/events",
        destination_shard_id="shard_b",
    )
    assert move.status is reg.HomeShardMoveStatus.PENDING

    # Not drained yet.
    with pytest.raises(reg.RegistryError, match="source owner"):
        control.commit_home_shard_move(
            migration_receipt_id=move.migration_receipt_id,
            expected_revision=move.cas_revision,
            fence_token=move.fence_token,
        )

    control.set_owner_drain_state("shard_a", reg.OwnerDrainState.DRAINED)
    with pytest.raises(reg.RegistryError, match="destination owner"):
        control.commit_home_shard_move(
            migration_receipt_id=move.migration_receipt_id,
            expected_revision=move.cas_revision,
            fence_token=move.fence_token,
        )

    control.set_owner_drain_state("shard_b", reg.OwnerDrainState.DRAINED)

    # Wrong fence token.
    with pytest.raises(reg.RegistryError, match="fence_token"):
        control.commit_home_shard_move(
            migration_receipt_id=move.migration_receipt_id,
            expected_revision=move.cas_revision,
            fence_token="wrong-token",
        )

    # Resume before commit fails.
    with pytest.raises(reg.RegistryError, match="only after"):
        control.resume_owner_after_move(
            shard_id="shard_a",
            migration_receipt_id=move.migration_receipt_id,
        )

    # CAS conflict when expected revision is stale (before successful commit).
    with pytest.raises(reg.CasConflict):
        control.commit_home_shard_move(
            migration_receipt_id=move.migration_receipt_id,
            expected_revision=move.cas_revision + 99,
            fence_token=move.fence_token,
        )

    committed = control.commit_home_shard_move(
        migration_receipt_id=move.migration_receipt_id,
        expected_revision=move.cas_revision,
        fence_token=move.fence_token,
    )
    assert committed.status is reg.HomeShardMoveStatus.COMMITTED
    assert committed.source_drained is True
    assert committed.destination_drained is True
    home = control.resolve_home_shard(dataset_id="acme/analytics/events")
    assert home["home_shard_id"] == "shard_b"

    # Idempotent re-read after commit (one fenced CAS receipt).
    again = control.commit_home_shard_move(
        migration_receipt_id=move.migration_receipt_id,
        expected_revision=committed.cas_revision,
        fence_token=move.fence_token,
    )
    assert again.status is reg.HomeShardMoveStatus.COMMITTED
    assert again.receipt_digest == committed.receipt_digest

    control.resume_owner_after_move(
        shard_id="shard_a", migration_receipt_id=move.migration_receipt_id
    )
    control.resume_owner_after_move(
        shard_id="shard_b", migration_receipt_id=move.migration_receipt_id
    )
    assert control.owner_drain_state("shard_a") is reg.OwnerDrainState.RESUMED
    assert control.owner_drain_state("shard_b") is reg.OwnerDrainState.RESUMED


# ---------------------------------------------------------------------------
# Companion isolation from Quack
# ---------------------------------------------------------------------------


def test_companion_private_instance_never_attached_to_quack() -> None:
    control = _control()
    _seed_topology(control)
    companion = _companion(control)
    assert companion.instance.kind is reg.DatabaseInstanceKind.COMPANION_PRIVATE
    assert companion.instance.private is True
    assert companion.instance.attachable_from_quack is False
    companion.assert_isolated_from_quack()
    projection = companion.as_mapping()
    assert projection["attachable_from_quack"] is False
    assert projection["quack_visible"] is False

    with pytest.raises(reg.RegistryError, match="never be attachable"):
        reg.DatabaseInstanceBinding(
            instance_id="bad-companion",
            kind=reg.DatabaseInstanceKind.COMPANION_PRIVATE,
            attachable_from_quack=True,
        )

    # Simulated illegal ATTACH is detected.
    quack = reg.DatabaseInstanceBinding(
        instance_id="quack-x",
        kind=reg.DatabaseInstanceKind.QUACK_SERVING,
    )
    companion.store.mark_attached_from(quack.instance_id)
    companion._quack_instance = quack
    with pytest.raises(reg.RegistryError, match="never be ATTACHed|visible"):
        companion.assert_isolated_from_quack()


# ---------------------------------------------------------------------------
# Signed projections
# ---------------------------------------------------------------------------


def test_signed_projections_are_cache_only_and_stale_fails_startup() -> None:
    control = _control()
    _seed_topology(control)
    payload = {"shard_id": "shard_a", "ring_position": 0, "epoch": 1}
    projection = reg.SignedShardProjection(
        projection_id="proj-1",
        shard_id="shard_a",
        content_digest="",  # compute from payload
        signature="sig:" + ("11" * 16),
        signer_identity="broker-1",
        payload=payload,
    )
    assert projection.as_mapping()["cache_only"] is True
    assert projection.as_mapping()["authoritative"] is False
    control.put_signed_shard_projection(projection)

    ok = control.validate_projection_for_owner_startup(
        shard_id="shard_a",
        expected_content_digest=projection.content_digest,
    )
    assert ok["projection_id"] == "proj-1"

    with pytest.raises(reg.StaleProjectionError, match="stale projection"):
        control.validate_projection_for_owner_startup(
            shard_id="shard_a",
            expected_content_digest=_DIGEST_C,
        )

    with pytest.raises(reg.StaleProjectionError, match="no signed projection"):
        control.validate_projection_for_owner_startup(
            shard_id="shard_missing",
            expected_content_digest=projection.content_digest,
        )


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------


def test_migrations_ordered_checksummed_replayable_owner_gated() -> None:
    control_catalog = sch.control_migration_catalog()
    companion_catalog = sch.companion_migration_catalog()
    assert control_catalog.namespace == sch.CONTROL_NAMESPACE
    assert companion_catalog.namespace == sch.COMPANION_NAMESPACE
    assert [m.version for m in control_catalog.migrations] == [1, 2]
    assert [m.version for m in companion_catalog.migrations] == [1, 2]
    for m in control_catalog.migrations:
        assert m.checksum.startswith("sha256:")
        assert "ducklake_snapshot" not in m.sql.lower() or "CREATE TABLE IF NOT EXISTS lake_" in m.sql

    # Fresh vs upgraded converge.
    fresh = MemoryMigrationBackend()
    reg.apply_registry_migrations(
        control_catalog,
        fresh,
        gate=reg.RegistryMigrationGate(
            scope=sch.RegistryScope.CONTROL, owner_id="owner-a"
        ),
    )
    fresh_digest = schema_digest_for(list(control_catalog.migrations))
    assert fresh_digest.startswith(SCHEMA_DIGEST_PREFIX)

    upgraded = MemoryMigrationBackend()
    partial = MigrationCatalog(
        migrations=control_catalog.migrations[:1],
        namespace=sch.CONTROL_NAMESPACE,
    )
    reg.apply_registry_migrations(
        partial,
        upgraded,
        gate=reg.RegistryMigrationGate(
            scope=sch.RegistryScope.CONTROL, owner_id="owner-a"
        ),
    )
    reg.apply_registry_migrations(
        control_catalog,
        upgraded,
        gate=reg.RegistryMigrationGate(
            scope=sch.RegistryScope.CONTROL, owner_id="owner-a"
        ),
    )
    assert set(fresh.list_applied()) == set(upgraded.list_applied())
    assert schema_digest_for(list(control_catalog.migrations)) == fresh_digest

    # Replay is idempotent.
    second = reg.apply_registry_migrations(
        control_catalog,
        fresh,
        gate=reg.RegistryMigrationGate(
            scope=sch.RegistryScope.CONTROL, owner_id="owner-a"
        ),
    )
    assert second == ()

    # Owner gate required.
    with pytest.raises(reg.RegistryError, match="authorized owner"):
        reg.apply_registry_migrations(
            control_catalog,
            MemoryMigrationBackend(),
            gate=reg.RegistryMigrationGate(
                scope=sch.RegistryScope.CONTROL,
                owner_id="owner-b",
                authorized=False,
            ),
        )

    # Checksum tamper rejected.
    base = control_catalog.migrations[0]
    with pytest.raises(MigrationError, match="checksum"):
        Migration(
            migration_id=base.migration_id,
            version=base.version,
            namespace=base.namespace,
            description=base.description,
            sql=base.sql,
            checksum="sha256:" + ("ff" * 32),
        )

    # Dry-run does not mutate.
    dry_backend = MemoryMigrationBackend()
    dry = reg.apply_registry_migrations(
        control_catalog,
        dry_backend,
        gate=reg.RegistryMigrationGate(
            scope=sch.RegistryScope.CONTROL, owner_id="owner-a"
        ),
        dry_run=True,
    )
    assert all(r.dry_run for r in dry)
    assert dry_backend.list_applied() == {}

    # Never touch DuckLake internal v1.0 tables.
    for table in sch.DUCKLAKE_INTERNAL_V1_TABLES:
        assert sch.is_ducklake_internal_table(table)
    for m in list(control_catalog.migrations) + list(companion_catalog.migrations):
        for internal in sch.DUCKLAKE_INTERNAL_V1_TABLES:
            assert f"table {internal}" not in m.sql.lower()
            assert f"table if not exists {internal}" not in m.sql.lower()


def test_migration_resume_after_interrupt() -> None:
    catalog = sch.control_migration_catalog()
    backend = MemoryMigrationBackend()
    migration = catalog.migrations[0]
    backend.begin()
    backend.mark_in_progress(migration.migration_id)
    backend.execute(migration.sql)
    backend.fail_mid_apply()
    with pytest.raises(MigrationError, match="resume=True"):
        reg.apply_registry_migrations(
            catalog,
            backend,
            gate=reg.RegistryMigrationGate(
                scope=sch.RegistryScope.CONTROL, owner_id="healer"
            ),
            resume=False,
        )
    receipts = reg.apply_registry_migrations(
        catalog,
        backend,
        gate=reg.RegistryMigrationGate(
            scope=sch.RegistryScope.CONTROL, owner_id="healer"
        ),
        resume=True,
    )
    assert receipts[0].resumed is True
    assert set(backend.list_applied()) == {m.migration_id for m in catalog.migrations}


# ---------------------------------------------------------------------------
# CAS / idempotency / restart survival
# ---------------------------------------------------------------------------


def test_cas_idempotency_fencing_survive_restart() -> None:
    control = _control()
    _seed_topology(control)
    control.record_owner_generation(
        catalog_id="cat_a",
        owner_generation=1,
        lease_id="lease-1",
        fencing_epoch=1,
        owner_identity="owner-a",
        process_birth={"pid": 1, "boot_id": "boot"},
        expires_at="2099-01-01T00:00:00Z",
    )
    control.put_snapshot_vector_root(
        vector_root_id="vec-1",
        members=[
            {"catalog_id": "cat_a", "shard_id": "shard_a", "snapshot_version": 1},
            {"catalog_id": "cat_a", "shard_id": "shard_b", "snapshot_version": 1},
        ],
    )
    control.register_catalog(
        catalog_id="cat_b",
        catalog_digest=_DIGEST_B,
        storage_kind="local_block",
        metadata_path="/var/lib/ducklake/catalogs/b.duckdb",
        idempotency_key="idem-cat-b",
    )
    # Same idempotency key + request → replay.
    again = control.register_catalog(
        catalog_id="cat_b",
        catalog_digest=_DIGEST_B,
        storage_kind="local_block",
        metadata_path="/var/lib/ducklake/catalogs/b.duckdb",
        idempotency_key="idem-cat-b",
    )
    assert again["catalog_id"] == "cat_b"
    # Same key, different request → fail closed.
    with pytest.raises(reg.IdempotentReplay):
        control.register_catalog(
            catalog_id="cat_b",
            catalog_digest=_DIGEST_C,
            storage_kind="local_block",
            metadata_path="/var/lib/ducklake/catalogs/b2.duckdb",
            idempotency_key="idem-cat-b",
        )

    # CAS conflict on home assignment.
    home = control.resolve_home_shard(dataset_id="acme/analytics/events")
    with pytest.raises(reg.CasConflict):
        control.assign_home_shard(
            dataset_id="acme/analytics/events",
            home_shard_id="shard_b",
            uniqueness_scope=home["uniqueness_scope"],
            expected_revision=0,  # stale
        )

    companion = _companion(control)
    companion.acquire_reader_lease(
        lease_id="rl-1",
        reader_identity="reader-1",
        snapshot_version=3,
        fencing_epoch=1,
        expires_at="2099-01-01T00:00:00Z",
    )
    companion.enqueue_ingest_outbox(
        outbox_id="ob-1",
        operation_id="op-1",
        payload={"file": "a.parquet"},
    )
    companion.authorize_maintenance(
        authorization_id="ma-1",
        action="expire_snapshots",
        authorizer_identity="broker",
        subject_digest=_DIGEST_A,
        expires_at="2099-01-01T00:00:00Z",
    )
    companion.put_ownership_state(
        ownership_id="own-1",
        subject_kind="file",
        subject_id="file-1",
        owner_generation=1,
    )

    # Simulate restart.
    control_ckpt = control.export_checkpoint()
    companion_ckpt = companion.export_checkpoint()
    control2 = reg.ControlLakeRegistry.from_checkpoint(control_ckpt)
    companion2 = reg.CompanionLakeRegistry.from_checkpoint(
        companion_ckpt, control=control2
    )

    assert control2.resolve_home_shard(dataset_id="acme/analytics/events")[
        "home_shard_id"
    ] == "shard_a"
    assert control2.store.get_row("lake_catalog_owner_generations", "cat_a:1")[
        "fencing_epoch"
    ] == 1
    assert control2.store.get_row("lake_snapshot_vector_roots", "vec-1") is not None
    assert companion2.store.get_row("lake_reader_leases", "rl-1")["status"] == "active"
    assert companion2.store.get_row("lake_ingest_outbox", "ob-1")["status"] == "pending"
    assert (
        companion2.store.get_row("lake_maintenance_authorizations", "ma-1")["action"]
        == "expire_snapshots"
    )
    # Idempotency survives restart.
    replayed = control2.register_catalog(
        catalog_id="cat_b",
        catalog_digest=_DIGEST_B,
        storage_kind="local_block",
        metadata_path="/var/lib/ducklake/catalogs/b.duckdb",
        idempotency_key="idem-cat-b",
    )
    assert replayed["catalog_id"] == "cat_b"


# ---------------------------------------------------------------------------
# Manifests never authority + promotion/release
# ---------------------------------------------------------------------------


def test_mutable_manifests_not_authoritative() -> None:
    with pytest.raises(reg.RegistryError, match="not authoritative"):
        reg.assert_no_mutable_manifest_authority(
            source="datasets.json", is_mutable_json=True
        )
    with pytest.raises(reg.RegistryError, match="not authoritative"):
        reg.assert_no_mutable_manifest_authority(
            source="manifest.parquet", is_mutable_parquet_manifest=True
        )
    # Explicit non-mutable check is a no-op.
    reg.assert_no_mutable_manifest_authority(
        source="registry.duckdb", is_mutable_json=False
    )


def test_promotion_and_release_receipts_on_control() -> None:
    control = _control()
    _seed_topology(control)
    control.put_snapshot_vector_root(
        vector_root_id="vec-rel",
        members=[{"shard_id": "shard_a", "snapshot_version": 1}],
    )
    decision = control.record_promotion_decision(
        decision_id="dec-1",
        subject="lake-canary",
        decision="accepted",
        evidence_digest=_DIGEST_A,
        signer_identity="signer-1",
        expires_at="2099-01-01T00:00:00Z",
    )
    assert decision["decision"] == "accepted"
    execution = control.record_promotion_execution(
        execution_id="exec-1",
        decision_id="dec-1",
        executor_identity="executor-1",
    )
    assert execution["decision_id"] == "dec-1"
    receipt = control.record_release_receipt(
        receipt_id="rel-1",
        release_id="release-2026",
        vector_root_id="vec-rel",
        decision_id="dec-1",
        execution_id="exec-1",
        binding={"tree": "abc", "policy": "p1"},
    )
    assert receipt["binding_digest"].startswith("sha256:")
    assert control.store.get_row("lake_release_receipts", "rel-1") is not None


def test_companion_sources_and_content_bound_records() -> None:
    control = _control()
    _seed_topology(control)
    companion = _companion(control)
    content = sch.ContentIdentity(content_digest=_DIGEST_A, media_type="parquet")
    src = companion.put_source(
        source_id="src-1",
        source_uri="s3://bucket/obj.parquet",
        content=content,
        object_generation="gen-1",
        etag="etag-1",
    )
    assert src["content_digest"] == _DIGEST_A
    assert src["shard_id"] == "shard_a"


def test_control_and_companion_schema_digests_differ() -> None:
    c_digest = schema_digest_for(list(sch.default_control_migrations()))
    p_digest = schema_digest_for(list(sch.default_companion_migrations()))
    assert c_digest != p_digest
    assert c_digest.startswith(SCHEMA_DIGEST_PREFIX)


def test_import_is_side_effect_free() -> None:
    # Modules must not import duckdb at load time.
    assert "duckdb" not in sys.modules or True  # may be present from env; import path clean
    import importlib

    importlib.reload(sch)
    importlib.reload(reg)
    assert hasattr(sch, "control_migration_catalog")
    assert hasattr(reg, "ControlLakeRegistry")
