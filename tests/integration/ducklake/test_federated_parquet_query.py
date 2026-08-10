"""Integration tests for federated Parquet queries across catalog shards (DQK-091).

Acceptance coverage:

* Queries aggregate at least two independently versioned Parquet datasets served
  by distinct DuckDB + Quack catalog shards
* The federation plan binds each shard endpoint, owner generation, snapshot,
  schema, and subresult digest
* No federating worker opens, copies, or network-mounts a catalog metadata file
* Field-ID remapping, missing columns, lossless type promotion, and partition
  evolution are deterministic
* File and row pruning are visible in bounded query evidence
* One unavailable catalog yields a typed policy-selected partial or failed
  result

Hermetic: in-memory Quack endpoint doubles and snapshot vectors (no duckdb /
network / catalog files required).
"""

from __future__ import annotations

import importlib
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

from ipfs_datasets_py.ducklake import contracts as c
from ipfs_datasets_py.ducklake import federation as fed
from ipfs_datasets_py.ducklake import snapshots as snap


# ---------------------------------------------------------------------------
# Fixtures / factories
# ---------------------------------------------------------------------------

_DIGEST_A = "sha256:" + ("ab" * 32)
_DIGEST_B = "sha256:" + ("cd" * 32)
_FILE_DIGEST = "sha256:" + ("11" * 32)


def _fields_a() -> tuple[c.FieldContract, ...]:
    return (
        c.FieldContract(
            field_id="f_event",
            name="event_id",
            field_type=c.FieldType.INT32,
            required=True,
            nullable=False,
        ),
        c.FieldContract(
            field_id="f_amount",
            name="amount",
            field_type=c.FieldType.INT32,
            nullable=True,
        ),
        c.FieldContract(
            field_id="f_region",
            name="region",
            field_type=c.FieldType.UTF8,
            nullable=True,
        ),
    )


def _fields_b() -> tuple[c.FieldContract, ...]:
    # Heterogeneous: amount is float64; event_id is int64 (lossless promotion);
    # f_extra is present only on B (missing on A → nullable in unified schema).
    return (
        c.FieldContract(
            field_id="f_event",
            name="event_id",
            field_type=c.FieldType.INT64,
            required=True,
            nullable=False,
        ),
        c.FieldContract(
            field_id="f_amount",
            name="amount",
            field_type=c.FieldType.FLOAT64,
            nullable=True,
        ),
        c.FieldContract(
            field_id="f_region",
            name="region",
            field_type=c.FieldType.UTF8,
            nullable=True,
        ),
        c.FieldContract(
            field_id="f_extra",
            name="extra_note",
            field_type=c.FieldType.UTF8,
            nullable=True,
        ),
    )


def _schema(contract_id: str, dataset_id: str, fields: tuple[c.FieldContract, ...]) -> c.SchemaContract:
    return c.SchemaContract(
        contract_id=contract_id,
        dataset_id=dataset_id,
        revision=1,
        fields=fields,
        tenant="acme",
        column_policy=c.ColumnPolicy(
            missing=c.MissingColumnPolicy.NULL_IF_NULLABLE,
            extra=c.ExtraColumnPolicy.DROP,
            require_field_ids=True,
        ),
    )


def _relation(
    *,
    dataset_id: str,
    catalog_id: str,
    port: int,
    snapshot_version: int,
    owner_generation: int,
    fields: tuple[c.FieldContract, ...],
    partition_keys: tuple[str, ...] = (),
    relation_kind: fed.LogicalRelationKind = fed.LogicalRelationKind.TABLE,
    relation_name: str = "events",
) -> fed.LogicalRelation:
    return fed.LogicalRelation(
        dataset_id=dataset_id,
        catalog_id=catalog_id,
        shard_id=f"shard_{catalog_id}",
        quack_endpoint_identity=f"quacks://127.0.0.1:{port}/{catalog_id}",
        relation_kind=relation_kind,
        schema_name="main",
        relation_name=relation_name,
        schema_contract=_schema(f"sc_{catalog_id}", dataset_id, fields),
        snapshot_version=snapshot_version,
        owner_generation=owner_generation,
        fencing_epoch=1,
        tenant="acme",
        partition_keys=partition_keys,
        source_revision=f"rev-{catalog_id}",
    )


def _dataset_pair() -> tuple[fed.VersionedLogicalDataset, fed.VersionedLogicalDataset]:
    a = fed.VersionedLogicalDataset(
        dataset_id="acme/analytics/events_east",
        relation=_relation(
            dataset_id="acme/analytics/events_east",
            catalog_id="cat_a",
            port=19001,
            snapshot_version=7,
            owner_generation=1,
            fields=_fields_a(),
            partition_keys=("f_region",),
        ),
        content_digest=_DIGEST_A,
        logical_alias="events_east",
    )
    b = fed.VersionedLogicalDataset(
        dataset_id="acme/analytics/events_west",
        relation=_relation(
            dataset_id="acme/analytics/events_west",
            catalog_id="cat_b",
            port=19002,
            snapshot_version=3,
            owner_generation=2,
            fields=_fields_b(),
            partition_keys=("f_region", "f_extra"),
        ),
        content_digest=_DIGEST_B,
        logical_alias="events_west",
    )
    return a, b


def _member(
    catalog_id: str,
    *,
    snapshot: int,
    owner_generation: int,
    port: int,
    datasets: tuple[str, ...] = (),
) -> snap.SnapshotVectorMember:
    return snap.SnapshotVectorMember(
        catalog_id=catalog_id,
        owner_generation=owner_generation,
        fencing_epoch=1,
        quack_endpoint_identity=f"quacks://127.0.0.1:{port}/{catalog_id}",
        catalog_global_snapshot_id=snapshot,
        schema_version="ducklake-schema@1",
        storage_root=f"s3://lake/{catalog_id}/data",
        logical_datasets=datasets,
        source_revisions={f"src-{catalog_id}": f"rev-{catalog_id}"},
        policy_decision_id="pol-fed-1",
        policy_decision={"decision_id": "pol-fed-1", "allowed": True},
        tenant_id="acme",
        catalog_digest=_DIGEST_A if catalog_id == "cat_a" else _DIGEST_B,
        shard_id=f"shard_{catalog_id}",
    )


def _vector_for(ds_a: fed.VersionedLogicalDataset, ds_b: fed.VersionedLogicalDataset) -> snap.SnapshotVector:
    return snap.capture_snapshot_vector(
        [
            _member(
                "cat_a",
                snapshot=ds_a.relation.snapshot_version,
                owner_generation=ds_a.relation.owner_generation,
                port=19001,
                datasets=(ds_a.logical_alias,),
            ),
            _member(
                "cat_b",
                snapshot=ds_b.relation.snapshot_version,
                owner_generation=ds_b.relation.owner_generation,
                port=19002,
                datasets=(ds_b.logical_alias,),
            ),
        ]
    )


def _fragments_a() -> list[fed.FileFragment]:
    return [
        fed.FileFragment(
            file_id="fa1",
            path="s3://lake/cat_a/data/region=east/part-001.parquet",
            content_digest=_FILE_DIGEST,
            row_count=100,
            byte_size=4096,
            partition={"f_region": "east"},
            column_stats={"f_amount": {"min": 1, "max": 50}, "f_event": {"min": 1, "max": 100}},
        ),
        fed.FileFragment(
            file_id="fa2",
            path="s3://lake/cat_a/data/region=west/part-002.parquet",
            content_digest=_FILE_DIGEST,
            row_count=80,
            byte_size=3072,
            partition={"f_region": "west"},
            column_stats={"f_amount": {"min": 10, "max": 20}, "f_event": {"min": 101, "max": 180}},
        ),
        fed.FileFragment(
            file_id="fa3",
            path="s3://lake/cat_a/data/region=east/part-003.parquet",
            content_digest=_FILE_DIGEST,
            row_count=50,
            byte_size=2048,
            partition={"f_region": "east"},
            column_stats={"f_amount": {"min": 200, "max": 300}, "f_event": {"min": 200, "max": 250}},
        ),
    ]


def _fragments_b() -> list[fed.FileFragment]:
    return [
        fed.FileFragment(
            file_id="fb1",
            path="s3://lake/cat_b/data/region=west/part-001.parquet",
            content_digest=_FILE_DIGEST,
            row_count=120,
            byte_size=5120,
            partition={"f_region": "west"},
            column_stats={"f_amount": {"min": 1.0, "max": 99.0}},
        ),
        fed.FileFragment(
            file_id="fb2",
            path="s3://lake/cat_b/data/region=north/part-002.parquet",
            content_digest=_FILE_DIGEST,
            row_count=40,
            byte_size=1024,
            partition={"f_region": "north"},
            column_stats={"f_amount": {"min": 0.0, "max": 5.0}},
        ),
    ]


def _engine_with_pair(
    *,
    b_available: bool = True,
) -> tuple[
    fed.FederatedParquetQueryEngine,
    fed.VersionedLogicalDataset,
    fed.VersionedLogicalDataset,
    snap.SnapshotVector,
]:
    ds_a, ds_b = _dataset_pair()
    vector = _vector_for(ds_a, ds_b)
    engine = fed.open_default_federation_engine()
    engine.register_dataset(ds_a, fragments=_fragments_a())
    engine.register_dataset(ds_b, fragments=_fragments_b())

    client_a = fed.InMemoryQuackShardClient(
        catalog_id="cat_a",
        quack_endpoint_identity=ds_a.relation.quack_endpoint_identity,
        rows_by_dataset={
            ds_a.dataset_id: [
                {"f_event": 1, "f_amount": 10, "f_region": "east"},
                {"f_event": 2, "f_amount": 20, "f_region": "east"},
                {"f_event": 3, "f_amount": 15, "f_region": "west"},
            ]
        },
        available=True,
        owner_generation=1,
        snapshot_version=7,
        schema_digest=ds_a.relation.schema_contract.schema_digest,
    )
    client_b = fed.InMemoryQuackShardClient(
        catalog_id="cat_b",
        quack_endpoint_identity=ds_b.relation.quack_endpoint_identity,
        rows_by_dataset={
            ds_b.dataset_id: [
                {"f_event": 2, "f_amount": 20.5, "f_region": "west", "f_extra": "note-2"},
                {"f_event": 4, "f_amount": 40.0, "f_region": "west", "f_extra": "note-4"},
            ]
        },
        available=b_available,
        owner_generation=2,
        snapshot_version=3,
        schema_digest=ds_b.relation.schema_contract.schema_digest,
    )
    engine.register_quack_client(client_a)
    engine.register_quack_client(client_b)
    for m in vector.members:
        engine.register_snapshot_evidence(
            m.catalog_id,
            {
                "catalog_id": m.catalog_id,
                "snapshot_version": m.catalog_global_snapshot_id,
                "owner_generation": m.owner_generation,
                "receipted": True,
            },
            member=m,
        )
    return engine, ds_a, ds_b, vector


# ---------------------------------------------------------------------------
# Side-effect free import
# ---------------------------------------------------------------------------


def test_federation_module_import_is_side_effect_free() -> None:
    mod = importlib.import_module("ipfs_datasets_py.ducklake.federation")
    assert mod.FEDERATION_SCHEMA.startswith("ipfs_datasets_py/ducklake-parquet-federation")
    assert "FederatedParquetQueryEngine" in mod.__all__
    assert mod.FEDERATION_IMPLEMENTATION_GENERATION.startswith("dqk-091")


# ---------------------------------------------------------------------------
# Aggregate ≥2 independently versioned datasets on distinct shards
# ---------------------------------------------------------------------------


def test_queries_aggregate_two_independent_shard_datasets() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair()
    result = engine.query(
        [ds_a.dataset_id, ds_b.dataset_id],
        snapshot_vector=vector,
        op=fed.FederationOp.UNION_ALL,
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
    )
    assert result.status is fed.FederationStatus.COMPLETE
    assert len(result.subresults) == 2
    catalogs = {sr.catalog_id for sr in result.subresults}
    assert catalogs == {"cat_a", "cat_b"}
    # Distinct independent snapshots
    snaps = {sr.snapshot_version for sr in result.subresults}
    assert snaps == {7, 3}
    # Combined rows from both shards
    assert len(result.rows) == 5  # 3 from A + 2 from B
    sources = {r["_catalog_id"] for r in result.rows}
    assert sources == {"cat_a", "cat_b"}
    assert result.result_digest.startswith("sha256:")


def test_inner_join_across_shards() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair()
    result = engine.query(
        [ds_a.dataset_id, ds_b.dataset_id],
        snapshot_vector=vector,
        op=fed.FederationOp.INNER_JOIN,
        join_keys=("f_event",),
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
    )
    assert result.status is fed.FederationStatus.COMPLETE
    # Only event_id=2 exists on both sides
    assert len(result.rows) == 1
    assert result.rows[0]["f_event"] == 2


# ---------------------------------------------------------------------------
# Plan binds endpoint, owner generation, snapshot, schema, subresult digest
# ---------------------------------------------------------------------------


def test_federation_plan_binds_endpoint_generation_snapshot_schema_digest() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair()
    plan = engine.compile(
        [ds_a.dataset_id, ds_b.dataset_id],
        snapshot_vector=vector,
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
    )
    assert plan.SCHEMA == fed.FEDERATION_PLAN_SCHEMA
    assert len(plan.subplans) == 2
    for sp in plan.subplans:
        binding = sp.binding
        assert binding.quack_endpoint_identity.startswith("quacks://")
        assert binding.owner_generation >= 1
        assert binding.snapshot_version >= 0
        assert binding.schema_digest.startswith("sha256:")
        assert binding.opens_catalog_file is False
        assert binding.catalog_metadata_path == ""
        body = binding.as_mapping()
        assert body["attach_target"] == "authenticated_quack_endpoint"
        assert "opens_catalog_file" in body and body["opens_catalog_file"] is False

    result = engine.execute(plan, snapshot_vector=vector)
    assert result.status is fed.FederationStatus.COMPLETE
    for sr in result.subresults:
        assert sr.subresult_digest.startswith("sha256:")
        assert sr.schema_digest.startswith("sha256:")
        assert sr.quack_endpoint_identity.startswith("quacks://")
        assert sr.owner_generation >= 1
        # Plan binding matches receipted subresult
        plan_binding = plan.binding_for(sr.catalog_id)
        assert plan_binding.snapshot_version == sr.snapshot_version
        assert plan_binding.owner_generation == sr.owner_generation
        assert plan_binding.schema_digest == sr.schema_digest


# ---------------------------------------------------------------------------
# No federating worker opens / copies / mounts catalog metadata files
# ---------------------------------------------------------------------------


def test_no_worker_opens_copies_or_mounts_catalog_metadata_file() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair()
    plan = engine.compile(
        [ds_a.dataset_id, ds_b.dataset_id],
        snapshot_vector=vector,
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
    )
    plan_map = plan.as_mapping()
    assert plan_map["opens_catalog_file"] is False
    for sp in plan.subplans:
        assert sp.binding.opens_catalog_file is False
        assert sp.as_mapping()["opens_catalog_file"] is False
        # Remote worker attach plan from snapshots layer
        member = vector.member_for(sp.binding.catalog_id)
        remote = snap.build_remote_worker_attach(member, vector_id=vector.vector_id)
        assert remote.opens_catalog_file is False
        assert remote.as_mapping()["attach_target"] == "authenticated_quack_endpoint"

    result = engine.execute(plan, snapshot_vector=vector)
    for sr in result.subresults:
        assert sr.opens_catalog_file is False
    assert result.as_mapping()["opens_catalog_file"] is False


@pytest.mark.parametrize(
    "bad_target",
    [
        "/var/lib/ducklake/catalogs/cat_a.duckdb",
        "file:///var/lib/ducklake/catalogs/cat_a.duckdb",
        "nfs://filer/share/cat_a.duckdb",
        "smb://filer/share/catalog.db",
        "s3://bucket/catalogs/cat_a.duckdb",
        "ducklake:/var/lib/ducklake/catalogs/cat_a.duckdb",
        "\\\\filer\\share\\cat.duckdb",
        "quacks://127.0.0.1:19001/cat_a.duckdb",
    ],
)
def test_catalog_file_targets_fail_closed(bad_target: str) -> None:
    with pytest.raises(fed.CatalogFileAccessError):
        fed.assert_no_catalog_file_access(bad_target)

    with pytest.raises(fed.CatalogFileAccessError):
        fed.LogicalRelation(
            dataset_id="acme/analytics/bad",
            catalog_id="cat_bad",
            shard_id="shard_bad",
            quack_endpoint_identity=bad_target,
            relation_kind=fed.LogicalRelationKind.TABLE,
            schema_name="main",
            relation_name="events",
            schema_contract=_schema("sc_bad", "acme/analytics/bad", _fields_a()),
            snapshot_version=1,
            owner_generation=1,
            tenant="acme",
        )


def test_shard_binding_rejects_opens_catalog_file_true() -> None:
    with pytest.raises(fed.CatalogFileAccessError):
        fed.ShardEndpointBinding(
            catalog_id="cat_a",
            shard_id="shard_a",
            quack_endpoint_identity="quacks://127.0.0.1:19001/cat_a",
            owner_generation=1,
            fencing_epoch=1,
            snapshot_version=7,
            schema_digest=_DIGEST_A,
            schema_revision=1,
            dataset_id="acme/analytics/events_east",
            opens_catalog_file=True,
        )


# ---------------------------------------------------------------------------
# Deterministic field-ID remapping, missing columns, promotion, partition evo
# ---------------------------------------------------------------------------


def test_field_id_remapping_missing_columns_promotion_partition_evolution_deterministic() -> None:
    ds_a, ds_b = _dataset_pair()
    # Reverse input order must not change reconciliation digest.
    rec1 = fed.reconcile_schemas([ds_a, ds_b])
    rec2 = fed.reconcile_schemas([ds_b, ds_a])
    assert rec1.schema_digest == rec2.schema_digest
    assert [f.field_id for f in rec1.unified_fields] == [
        f.field_id for f in rec2.unified_fields
    ]

    # Lossless LUB: int32/int64 → int64; int32/float64 → float64
    by_id = {f.field_id: f for f in rec1.unified_fields}
    assert by_id["f_event"].field_type is c.FieldType.INT64
    assert by_id["f_amount"].field_type is c.FieldType.FLOAT64
    # Missing on A → nullable
    assert by_id["f_extra"].nullable is True

    # Remappings for A include missing f_extra
    remaps_a = rec1.remappings[ds_a.dataset_id]
    missing = [r for r in remaps_a if r.missing]
    assert any(r.target_field_id == "f_extra" for r in missing)
    promoted_amount = [
        r for r in remaps_a if r.target_field_id == "f_amount" and r.promoted
    ]
    assert len(promoted_amount) == 1
    assert promoted_amount[0].source_type is c.FieldType.INT32
    assert promoted_amount[0].target_type is c.FieldType.FLOAT64

    # Partition evolution unions keys from both sources, sorted
    pe = rec1.partition_evolution
    assert pe.partition_field_ids == ("f_extra", "f_region")
    assert set(pe.source_partitions[ds_a.dataset_id]) == {"f_region"}
    assert set(pe.source_partitions[ds_b.dataset_id]) == {"f_extra", "f_region"}

    # least_upper_bound is order-independent
    assert fed.least_upper_bound_type(
        [c.FieldType.INT32, c.FieldType.INT64]
    ) is fed.least_upper_bound_type([c.FieldType.INT64, c.FieldType.INT32])


def test_lossy_type_promotion_rejected_during_remapping() -> None:
    # utf8 cannot promote to int32
    src = c.SchemaContract(
        contract_id="lossy_src",
        dataset_id="acme/analytics/lossy",
        revision=1,
        fields=(
            c.FieldContract(
                field_id="f_x",
                name="x",
                field_type=c.FieldType.UTF8,
            ),
        ),
        tenant="acme",
    )
    target = (
        c.FieldContract(
            field_id="f_x",
            name="x",
            field_type=c.FieldType.INT32,
        ),
    )
    with pytest.raises(fed.SchemaReconciliationError):
        fed.deterministic_field_remapping(src, target)


# ---------------------------------------------------------------------------
# File and row pruning visible in bounded query evidence
# ---------------------------------------------------------------------------


def test_file_and_row_pruning_visible_in_bounded_evidence() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair()
    predicates = (
        fed.Predicate(field_id="f_region", op="eq", value="east"),
        fed.Predicate(field_id="f_amount", op="lt", value=100),
    )
    plan = engine.compile(
        [ds_a.dataset_id, ds_b.dataset_id],
        snapshot_vector=vector,
        predicates=predicates,
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
    )
    # Shard A: fa1 selected (east + amount max 50); fa2 pruned by partition (west);
    # fa3 pruned by stats (amount min 200).
    sp_a = next(sp for sp in plan.subplans if sp.binding.catalog_id == "cat_a")
    assert sp_a.pruning.files_considered == 3
    assert sp_a.pruning.files_selected == 1
    assert sp_a.pruning.files_pruned == 2
    assert "fa1" in sp_a.pruning.selected_file_ids
    assert "fa2" in sp_a.pruning.pruned_file_ids
    assert "fa3" in sp_a.pruning.pruned_file_ids
    assert sp_a.pruning.partition_pruned_files >= 1
    assert sp_a.pruning.statistics_pruned_files >= 1
    assert sp_a.pruning.rows_pruned == sp_a.pruning.rows_considered - sp_a.pruning.rows_selected
    assert sp_a.pruning.rows_pruned > 0

    # Evidence is carried into the federated result
    result = engine.execute(plan, snapshot_vector=vector)
    assert len(result.pruning_evidence) == 2
    for ev in result.pruning_evidence:
        assert "files_considered" in ev
        assert "files_pruned" in ev
        assert "rows_pruned" in ev
        assert "predicates" in ev
        assert ev["files_selected"] + ev["files_pruned"] == ev["files_considered"]
        assert ev["rows_selected"] + ev["rows_pruned"] == ev["rows_considered"]


def test_prune_fragments_is_deterministic() -> None:
    frags = _fragments_a()
    # Reverse order of input fragments
    preds = (fed.Predicate(field_id="f_region", op="eq", value="east"),)
    selected1, ev1 = fed.prune_fragments(list(reversed(frags)), preds)
    selected2, ev2 = fed.prune_fragments(frags, preds)
    assert [f.file_id for f in selected1] == [f.file_id for f in selected2]
    assert dict(ev1.as_mapping()) == dict(ev2.as_mapping())


# ---------------------------------------------------------------------------
# Unavailable catalog → typed policy-selected partial or failed result
# ---------------------------------------------------------------------------


def test_unavailable_catalog_yields_partial_under_partial_policy() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair(b_available=False)
    result = engine.query(
        [ds_a.dataset_id, ds_b.dataset_id],
        snapshot_vector=vector,
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
        partial_failure_policy=fed.PartialFailurePolicy.PARTIAL,
    )
    assert result.status is fed.FederationStatus.PARTIAL
    assert len(result.failures) >= 1
    kinds = {f.kind for f in result.failures}
    assert fed.FailureKind.CATALOG_UNAVAILABLE in kinds
    # Rows only from the available catalog
    assert all(r["_catalog_id"] == "cat_a" for r in result.rows)
    assert len(result.rows) == 3
    # Typed failure payload
    for failure in result.failures:
        body = failure.as_mapping()
        assert body["kind"] in {k.value for k in fed.FailureKind}
        assert body["catalog_id"]
        assert body["dataset_id"]


def test_unavailable_catalog_yields_failed_under_require_all_policy() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair(b_available=False)
    result = engine.query(
        [ds_a.dataset_id, ds_b.dataset_id],
        snapshot_vector=vector,
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
        partial_failure_policy=fed.PartialFailurePolicy.REQUIRE_ALL,
    )
    assert result.status is fed.FederationStatus.FAILED
    assert len(result.rows) == 0
    assert any(f.kind is fed.FailureKind.CATALOG_UNAVAILABLE for f in result.failures)


def test_unavailable_catalog_fail_policy() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair(b_available=False)
    result = engine.query(
        [ds_a.dataset_id, ds_b.dataset_id],
        snapshot_vector=vector,
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
        partial_failure_policy=fed.PartialFailurePolicy.FAIL,
    )
    assert result.status is fed.FederationStatus.FAILED
    assert result.rows == ()


# ---------------------------------------------------------------------------
# Tenant policy
# ---------------------------------------------------------------------------


def test_tenant_policy_denies_cross_tenant() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair()
    with pytest.raises(fed.TenantPolicyError):
        engine.compile(
            [ds_a.dataset_id, ds_b.dataset_id],
            snapshot_vector=vector,
            tenant_policy=fed.TenantPolicy(tenant_id="other-tenant"),
        )


def test_tenant_policy_dataset_allowlist() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair()
    with pytest.raises(fed.TenantPolicyError):
        engine.compile(
            [ds_a.dataset_id, ds_b.dataset_id],
            snapshot_vector=vector,
            tenant_policy=fed.TenantPolicy(
                tenant_id="acme",
                allowed_datasets=frozenset({ds_a.dataset_id}),  # missing ds_b
            ),
        )


# ---------------------------------------------------------------------------
# Plan invariants
# ---------------------------------------------------------------------------


def test_plan_requires_two_distinct_catalog_shards() -> None:
    ds_a, _ = _dataset_pair()
    # Two datasets on the same catalog — rejected
    ds_same = fed.VersionedLogicalDataset(
        dataset_id="acme/analytics/events_east_v2",
        relation=_relation(
            dataset_id="acme/analytics/events_east_v2",
            catalog_id="cat_a",  # same catalog
            port=19001,
            snapshot_version=7,
            owner_generation=1,
            fields=_fields_a(),
        ),
    )
    vector = snap.capture_snapshot_vector(
        [
            _member("cat_a", snapshot=7, owner_generation=1, port=19001),
        ]
    )
    with pytest.raises(fed.FederationError):
        fed.compile_federation_plan(
            [ds_a, ds_same],
            snapshot_vector=vector,
            tenant_policy=fed.TenantPolicy(tenant_id="acme"),
        )


def test_views_and_tables_map_to_logical_datasets() -> None:
    table = fed.VersionedLogicalDataset(
        dataset_id="acme/analytics/events_table",
        relation=_relation(
            dataset_id="acme/analytics/events_table",
            catalog_id="cat_a",
            port=19001,
            snapshot_version=1,
            owner_generation=1,
            fields=_fields_a(),
            relation_kind=fed.LogicalRelationKind.TABLE,
            relation_name="events",
        ),
    )
    view = fed.VersionedLogicalDataset(
        dataset_id="acme/analytics/events_view",
        relation=_relation(
            dataset_id="acme/analytics/events_view",
            catalog_id="cat_b",
            port=19002,
            snapshot_version=2,
            owner_generation=1,
            fields=_fields_b(),
            relation_kind=fed.LogicalRelationKind.VIEW,
            relation_name="events_v",
        ),
    )
    vector = snap.capture_snapshot_vector(
        [
            _member("cat_a", snapshot=1, owner_generation=1, port=19001),
            _member("cat_b", snapshot=2, owner_generation=1, port=19002),
        ]
    )
    plan = fed.compile_federation_plan(
        [table, view],
        snapshot_vector=vector,
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
    )
    kinds = {
        ds.dataset_id: ds.relation.relation_kind
        for ds in (table, view)
    }
    assert kinds[table.dataset_id] is fed.LogicalRelationKind.TABLE
    assert kinds[view.dataset_id] is fed.LogicalRelationKind.VIEW
    assert any("events_v" in sp.qualified_relation for sp in plan.subplans)


def test_combine_only_snapshot_receipted_results() -> None:
    engine, ds_a, ds_b, vector = _engine_with_pair()
    plan = engine.compile(
        [ds_a.dataset_id, ds_b.dataset_id],
        snapshot_vector=vector,
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
    )
    # Forge a "success" without digest and with wrong snapshot
    forged = fed.ShardSubresult(
        subplan_id=plan.subplans[0].subplan_id,
        dataset_id=plan.subplans[0].dataset_id,
        catalog_id=plan.subplans[0].binding.catalog_id,
        status=fed.ShardSubresultStatus.SUCCEEDED,
        rows=({"f_event": 99},),
        subresult_digest="",  # missing
        snapshot_version=plan.subplans[0].binding.snapshot_version,
        owner_generation=plan.subplans[0].binding.owner_generation,
        schema_digest=plan.subplans[0].binding.schema_digest,
        quack_endpoint_identity=plan.subplans[0].binding.quack_endpoint_identity,
    )
    # Actually empty digest gets auto-filled on SUCCEEDED — force digest empty
    # by using RECEIPT path: wrong snapshot version
    forged_wrong_snap = fed.ShardSubresult(
        subplan_id=plan.subplans[0].subplan_id,
        dataset_id=plan.subplans[0].dataset_id,
        catalog_id=plan.subplans[0].binding.catalog_id,
        status=fed.ShardSubresultStatus.SUCCEEDED,
        rows=({"f_event": 99},),
        subresult_digest="sha256:" + ("ee" * 32),
        snapshot_version=plan.subplans[0].binding.snapshot_version + 99,
        owner_generation=plan.subplans[0].binding.owner_generation,
        schema_digest=plan.subplans[0].binding.schema_digest,
        quack_endpoint_identity=plan.subplans[0].binding.quack_endpoint_identity,
    )
    good_b = fed.ShardSubresult(
        subplan_id=plan.subplans[1].subplan_id,
        dataset_id=plan.subplans[1].dataset_id,
        catalog_id=plan.subplans[1].binding.catalog_id,
        status=fed.ShardSubresultStatus.SUCCEEDED,
        rows=({"f_event": 4, "f_amount": 1.0, "f_region": "west", "f_extra": "x"},),
        subresult_digest="sha256:" + ("ff" * 32),
        snapshot_version=plan.subplans[1].binding.snapshot_version,
        owner_generation=plan.subplans[1].binding.owner_generation,
        schema_digest=plan.subplans[1].binding.schema_digest,
        quack_endpoint_identity=plan.subplans[1].binding.quack_endpoint_identity,
    )
    combined = fed.combine_subresults(plan, [forged_wrong_snap, good_b])
    assert any(f.kind is fed.FailureKind.SNAPSHOT_MISMATCH for f in combined.failures)
    # Under PARTIAL default, only receipted B rows survive
    assert combined.status is fed.FederationStatus.PARTIAL
    assert all(r.get("_catalog_id") == "cat_b" for r in combined.rows)


def test_schema_constants_stable() -> None:
    assert fed.FEDERATION_SCHEMA.endswith("@1")
    assert fed.FEDERATION_PLAN_SCHEMA.endswith("@1")
    assert fed.FEDERATION_RESULT_SCHEMA.endswith("@1")
    assert fed.SHARD_SUBPLAN_SCHEMA.endswith("@1")
    assert fed.SHARD_SUBRESULT_SCHEMA.endswith("@1")
    assert fed.PRUNING_EVIDENCE_SCHEMA.endswith("@1")
    assert fed.SCHEMA_RECONCILIATION_SCHEMA.endswith("@1")


def test_push_subplan_never_attaches_catalog_file() -> None:
    ds_a, ds_b = _dataset_pair()
    vector = _vector_for(ds_a, ds_b)
    plan = fed.compile_federation_plan(
        [ds_a, ds_b],
        snapshot_vector=vector,
        fragments_by_dataset={
            ds_a.dataset_id: _fragments_a(),
            ds_b.dataset_id: _fragments_b(),
        },
        tenant_policy=fed.TenantPolicy(tenant_id="acme"),
    )
    client = fed.InMemoryQuackShardClient(
        catalog_id="cat_a",
        quack_endpoint_identity=ds_a.relation.quack_endpoint_identity,
        rows_by_dataset={ds_a.dataset_id: [{"f_event": 1, "f_amount": 1, "f_region": "east"}]},
        snapshot_version=7,
    )
    sp = next(s for s in plan.subplans if s.binding.catalog_id == "cat_a")
    member = vector.member_for("cat_a")
    result = fed.push_subplan_via_quack(client, sp, member=member)
    assert result.status is fed.ShardSubresultStatus.SUCCEEDED
    assert result.opens_catalog_file is False
    assert client.opened_catalog_file is False
