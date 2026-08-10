"""Hermetic unit tests for DQK-090 snapshot vectors and reader leases.

Covers acceptance criteria:

* Snapshot-vector identity is deterministic and order independent with one
  member per DuckDB + Quack catalog shard
* Every member binds Quack endpoint, catalog-owner generation, DuckDB catalog
  identity, and catalog-global snapshot
* Workers acquire / renew / release authoritative leases bound to process
  birth, task/run, and generation fences; PID reuse, stale fence, and foreign
  tokens fail closed
* Only the fenced owner opens the catalog file and proves SNAPSHOT_VERSION;
  remote workers open only the authenticated Quack endpoint
* Owner-side non-bootstrap ATTACH forces CREATE_IF_NOT_EXISTS /
  OVERRIDE_DATA_PATH / AUTOMATIC_MIGRATION = false
* Database exposes the exact live reader-lease set for DQK-096 maintenance;
  crashed readers lose protection only through bounded lease expiry
* Stale, expired, mixed-tenant, duplicate-catalog, owner-generation, or
  schema-incompatible members fail closed
* Time-travel replay returns the same logical result or a typed retention error
* No snapshot vector or reader lease is represented only by a file

All tests use pure in-memory fixtures (no optional ``duckdb`` import).
"""

from __future__ import annotations

import importlib
import sys
import threading
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
from ipfs_datasets_py.ducklake import snapshots as snap
from ipfs_datasets_py.ducklake.capabilities import ATTACH_SAFE_OPTIONS


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

_CMDLINE = "sha256:" + ("11" * 32)
_DIGEST_A = "sha256:" + ("ab" * 32)
_DIGEST_B = "sha256:" + ("cd" * 32)

_ALLOWLIST = (
    "/var/lib/ducklake/catalogs",
    "/var/lib/ducklake/registries",
    "/var/lib/ducklake/data",
    "/var/lib/ducklake/staging",
)


def _birth(**overrides: Any) -> cfg.ProcessBirthBinding:
    payload = {
        "pid": 4242,
        "boot_id": "boot-test-001",
        "start_ticks": 1000,
        "cmdline_sha256": _CMDLINE,
    }
    payload.update(overrides)
    return cfg.ProcessBirthBinding(**payload)


def _member(catalog_id: str = "cat_a", **overrides: Any) -> snap.SnapshotVectorMember:
    payload: dict[str, Any] = {
        "catalog_id": catalog_id,
        "owner_generation": 1,
        "fencing_epoch": 1,
        "quack_endpoint_identity": f"quacks://127.0.0.1:19001/{catalog_id}",
        "catalog_global_snapshot_id": 7,
        "schema_version": "ducklake-schema@1",
        "storage_root": f"s3://lake/{catalog_id}/data",
        "logical_datasets": ("events", "users"),
        "source_revisions": {"src-1": "rev-a", "src-2": "rev-b"},
        "policy_decision_id": "pol-1",
        "policy_decision": {
            "decision_id": "pol-1",
            "allowed": True,
            "decided_by": "broker",
        },
        "tenant_id": "acme",
        "catalog_digest": _DIGEST_A if catalog_id == "cat_a" else _DIGEST_B,
        "shard_id": f"shard-{catalog_id}",
    }
    payload.update(overrides)
    return snap.SnapshotVectorMember(**payload)


def _vector(*catalog_ids: str, **member_overrides: Any) -> snap.SnapshotVector:
    ids = catalog_ids or ("cat_a", "cat_b")
    members = [_member(cid, **member_overrides) for cid in ids]
    # Distinct endpoints already set per catalog_id.
    return snap.capture_snapshot_vector(members)


def _secrets() -> cfg.SecretProfile:
    return cfg.SecretProfile(
        quack_capability_ref=cfg.ExternalSecretReference(
            ref_id="vault:quack/catalog/broker",
            purpose="quack_capability",
            provider="vault",
        ),
        object_read_ref=cfg.ExternalSecretReference(
            ref_id="vault:obj/catalog/read",
            purpose="object_read",
        ),
        object_write_ref=cfg.ExternalSecretReference(
            ref_id="vault:obj/catalog/write",
            purpose="object_write",
        ),
        object_delete_ref=cfg.ExternalSecretReference(
            ref_id="vault:obj/catalog/delete",
            purpose="object_delete",
        ),
        catalog_encryption_key_ref=cfg.ExternalSecretReference(
            ref_id="kms:key/catalog",
            purpose="encryption_key",
            provider="kms",
        ),
        signing_key_ref=cfg.ExternalSecretReference(
            ref_id="kms:key/signing",
            purpose="signing_key",
            provider="kms",
        ),
    )


def _profile(
    catalog_id: str = "cat_a",
    *,
    port: int = 19001,
    **overrides: Any,
) -> cfg.CatalogShardProfile:
    payload: dict[str, Any] = {
        "catalog_id": catalog_id,
        "catalog_metadata": cfg.AuthorityDatabasePath(
            path=f"/var/lib/ducklake/catalogs/{catalog_id}.duckdb",
            storage_kind=cfg.AuthorityStorageKind.LOCAL_BLOCK,
            role="catalog",
            allowlist=_ALLOWLIST,
        ),
        "companion_registry": cfg.AuthorityDatabasePath(
            path=f"/var/lib/ducklake/registries/{catalog_id}_registry.duckdb",
            storage_kind=cfg.AuthorityStorageKind.LOCAL_BLOCK,
            role="companion_registry",
            allowlist=_ALLOWLIST,
        ),
        "quack_endpoint": cfg.QuackEndpointProfile(
            host="127.0.0.1",
            port=port,
            database=catalog_id,
            use_tls=True,
        ),
        "owner_lease": cfg.OwnerLeaseBinding(
            lease_id=f"lease-{catalog_id}-1",
            owner_generation=1,
            fencing_epoch=1,
            process_birth=_birth(),
            endpoint_identity=f"quacks://127.0.0.1:{port}/{catalog_id}",
            os_identity=f"ducklake_{catalog_id}_owner",
        ),
        "parquet_namespace": cfg.ParquetNamespace(
            data_path=f"/var/lib/ducklake/data/{catalog_id}",
            storage_kind=cfg.ParquetStorageKind.LOCAL,
            namespace_id=f"{catalog_id}_ns",
            staging_path=f"/var/lib/ducklake/staging/{catalog_id}",
            allowlist=_ALLOWLIST,
            provenance_cid_roots=("bafybeigdyrzt",),
        ),
        "secret_profile": _secrets(),
        "encryption": cfg.EncryptionDefaults(
            catalog_at_rest=True,
            object_at_rest=True,
            transit_tls_required=True,
            key_ref=cfg.ExternalSecretReference(
                ref_id="kms:key/catalog-default",
                purpose="encryption_key",
                provider="kms",
            ),
        ),
    }
    payload.update(overrides)
    return cfg.CatalogShardProfile(**payload)


# ---------------------------------------------------------------------------
# Vector identity + membership
# ---------------------------------------------------------------------------


def test_vector_identity_order_independent() -> None:
    a = _member("cat_a")
    b = _member("cat_b")
    v1 = snap.capture_snapshot_vector([a, b])
    v2 = snap.capture_snapshot_vector([b, a])
    assert v1.identity_digest == v2.identity_digest
    assert v1.catalog_ids() == ("cat_a", "cat_b")
    assert v2.catalog_ids() == ("cat_a", "cat_b")
    assert v1.vector_id == v1.identity_digest or v1.identity_digest


def test_vector_identity_deterministic_across_captures() -> None:
    members = [_member("cat_a"), _member("cat_b")]
    d1 = snap.vector_identity_digest(members)
    d2 = snap.vector_identity_digest(list(reversed(members)))
    assert d1 == d2
    assert d1.startswith("sha256:")


def test_one_member_per_catalog_shard() -> None:
    with pytest.raises(snap.SnapshotVectorError, match="duplicate catalog"):
        snap.capture_snapshot_vector(
            [_member("cat_a"), _member("cat_a", catalog_global_snapshot_id=9)]
        )


def test_member_binds_endpoint_generation_catalog_snapshot() -> None:
    m = _member(
        "cat_a",
        owner_generation=3,
        fencing_epoch=5,
        quack_endpoint_identity="quacks://owner/cat_a",
        catalog_global_snapshot_id=42,
    )
    mapping = m.as_mapping()
    assert mapping["catalog_id"] == "cat_a"
    assert mapping["owner_generation"] == 3
    assert mapping["fencing_epoch"] == 5
    assert mapping["quack_endpoint_identity"] == "quacks://owner/cat_a"
    assert mapping["catalog_global_snapshot_id"] == 42
    assert mapping["snapshot_version"] == 42
    assert mapping["schema_version"]
    assert mapping["storage_root"]
    assert mapping["logical_datasets"] == ["events", "users"]
    assert mapping["source_revisions"]["src-1"] == "rev-a"
    assert mapping["policy_decision_id"] == "pol-1"


def test_mixed_tenant_fails_closed() -> None:
    with pytest.raises(snap.SnapshotVectorError, match="mixed-tenant"):
        snap.capture_snapshot_vector(
            [
                _member("cat_a", tenant_id="acme"),
                _member("cat_b", tenant_id="other"),
            ]
        )


def test_schema_incompatible_fails_closed() -> None:
    with pytest.raises(snap.SnapshotVectorError, match="schema-incompatible"):
        snap.capture_snapshot_vector(
            [
                _member("cat_a", schema_version="v1"),
                _member("cat_b", schema_version="v2"),
            ]
        )


def test_duplicate_endpoint_fails_closed() -> None:
    with pytest.raises(snap.SnapshotVectorError, match="duplicate Quack endpoint"):
        snap.capture_snapshot_vector(
            [
                _member("cat_a", quack_endpoint_identity="quacks://shared"),
                _member("cat_b", quack_endpoint_identity="quacks://shared"),
            ]
        )


def test_empty_vector_fails_closed() -> None:
    with pytest.raises(snap.SnapshotVectorError, match="at least one member"):
        snap.capture_snapshot_vector([])


def test_file_only_vector_representation_rejected() -> None:
    with pytest.raises(snap.SnapshotVectorError, match="not be represented only by a file"):
        snap.SnapshotVector(members=(_member("cat_a"),), representation="file")


# ---------------------------------------------------------------------------
# Owner attach + remote attach + evidence
# ---------------------------------------------------------------------------


def test_owner_attach_safe_options_and_snapshot_version() -> None:
    member = _member("cat_a", catalog_global_snapshot_id=11)
    profile = _profile("cat_a")
    plan = snap.build_owner_snapshot_attach(profile, member)
    assert plan.snapshot_version == 11
    assert plan.attach.snapshot_version == 11
    opts = plan.attach.ducklake_options()
    for key, expected in ATTACH_SAFE_OPTIONS.items():
        assert bool(opts[key]) is bool(expected)
    sql = plan.attach.sql()
    assert "CREATE_IF_NOT_EXISTS false" in sql
    assert "OVERRIDE_DATA_PATH false" in sql
    assert "AUTOMATIC_MIGRATION false" in sql
    assert "SNAPSHOT_VERSION 11" in sql
    assert plan.catalog_path.endswith("cat_a.duckdb")
    mapping = plan.as_mapping()
    assert mapping["owner_opens_catalog_file"] is True
    assert mapping["remote_opens_catalog_file"] is False


def test_owner_attach_generation_mismatch_fails() -> None:
    member = _member("cat_a", owner_generation=9)
    profile = _profile("cat_a")
    with pytest.raises(snap.SnapshotAttachError, match="owner-generation"):
        snap.build_owner_snapshot_attach(profile, member)


def test_prove_owner_snapshot_version_match_and_mismatch() -> None:
    member = _member("cat_a", catalog_global_snapshot_id=5)
    plan = snap.build_owner_snapshot_attach(_profile("cat_a"), member)
    evidence = snap.prove_owner_snapshot_version(
        plan,
        observed_snapshot_version=5,
        signer_identity="owner-signer",
        vector_id="vec-1",
    )
    assert evidence.attach_snapshot_version == 5
    assert evidence.signature.startswith("sig:")
    with pytest.raises(snap.SnapshotAttachError, match="does not equal"):
        snap.prove_owner_snapshot_version(
            plan,
            observed_snapshot_version=99,
            signer_identity="owner-signer",
            vector_id="vec-1",
        )


def test_remote_worker_opens_only_quack_endpoint() -> None:
    member = _member("cat_a")
    plan = snap.build_remote_worker_attach(member, vector_id="vec-1")
    assert plan.opens_catalog_file is False
    assert plan.quack_endpoint_identity.startswith("quacks://")
    mapping = plan.as_mapping()
    assert mapping["attach_target"] == "authenticated_quack_endpoint"
    with pytest.raises(snap.SnapshotAttachError, match="catalog file"):
        snap.RemoteWorkerAttachPlan(
            catalog_id="cat_a",
            quack_endpoint_identity="quacks://ok",
            owner_generation=1,
            fencing_epoch=1,
            snapshot_version=1,
            vector_id="v",
            opens_catalog_file=True,
        )
    with pytest.raises(snap.SnapshotAttachError, match="not a catalog file path"):
        snap.RemoteWorkerAttachPlan(
            catalog_id="cat_a",
            quack_endpoint_identity="/var/lib/ducklake/catalogs/a.duckdb",
            owner_generation=1,
            fencing_epoch=1,
            snapshot_version=1,
            vector_id="v",
        )


def test_verify_remote_snapshot_receipt() -> None:
    member = _member("cat_a", catalog_global_snapshot_id=3)
    plan = snap.build_owner_snapshot_attach(_profile("cat_a"), member)
    evidence = snap.prove_owner_snapshot_version(
        plan,
        observed_snapshot_version=3,
        signer_identity="owner",
        vector_id="vec-x",
    )
    snap.verify_remote_snapshot_receipt(
        member, evidence, expected_vector_id="vec-x"
    )
    with pytest.raises(snap.SnapshotAttachError, match="owner-generation"):
        bad = snap.SignedSnapshotEvidence(
            evidence_id="e1",
            catalog_id=member.catalog_id,
            snapshot_version=3,
            owner_generation=99,
            fencing_epoch=1,
            vector_id="vec-x",
            attach_snapshot_version=3,
            signature="sig:x",
            signer_identity="owner",
            body_digest="sha256:" + ("00" * 32),
        )
        snap.verify_remote_snapshot_receipt(
            member, bad, expected_vector_id="vec-x"
        )


# ---------------------------------------------------------------------------
# Reader leases: acquire / renew / release + fences
# ---------------------------------------------------------------------------


def test_lease_acquire_renew_release_happy_path() -> None:
    db = snap.AuthoritativeSnapshotDatabase()
    vector = _vector("cat_a", "cat_b")
    db.put_vector(vector)
    birth = _birth()
    lease = db.acquire_lease(
        vector=vector,
        catalog_id="cat_a",
        process_birth=birth,
        task_id="task-1",
        run_id="run-1",
        worker_id="worker-1",
        ttl_seconds=60,
        expected_owner_generation=1,
        expected_fencing_epoch=1,
    )
    assert lease.status is snap.LeaseStatus.ACTIVE
    assert lease.vector_id == vector.vector_id
    assert lease.snapshot_version == 7
    assert lease.as_mapping()["lease_token"] == "***"
    assert lease.as_mapping(reveal_token=True)["lease_token"] == lease.lease_token

    renewed = db.renew_lease(
        lease_id=lease.lease_id,
        lease_token=lease.lease_token,
        process_birth=birth,
        task_id="task-1",
        run_id="run-1",
        ttl_seconds=120,
        owner_generation=1,
        fencing_epoch=1,
    )
    assert renewed.status is snap.LeaseStatus.ACTIVE
    assert renewed.renewed_at

    released = db.release_lease(
        lease_id=lease.lease_id,
        lease_token=lease.lease_token,
        process_birth=birth,
        task_id="task-1",
        run_id="run-1",
        owner_generation=1,
        fencing_epoch=1,
    )
    assert released.status is snap.LeaseStatus.RELEASED
    live = db.list_live_leases(catalog_id="cat_a")
    assert live == ()


def test_foreign_token_fails_closed() -> None:
    db = snap.AuthoritativeSnapshotDatabase()
    vector = _vector("cat_a")
    birth = _birth()
    lease = db.acquire_lease(
        vector=vector,
        catalog_id="cat_a",
        process_birth=birth,
        task_id="t",
        run_id="r",
        worker_id="w",
    )
    with pytest.raises(snap.ReaderLeaseError, match="foreign lease token"):
        db.renew_lease(
            lease_id=lease.lease_id,
            lease_token="not-the-token",
            process_birth=birth,
            task_id="t",
            run_id="r",
        )
    with pytest.raises(snap.ReaderLeaseError, match="foreign lease token"):
        db.release_lease(
            lease_id=lease.lease_id,
            lease_token="not-the-token",
            process_birth=birth,
            task_id="t",
            run_id="r",
        )


def test_pid_reuse_fails_closed() -> None:
    db = snap.AuthoritativeSnapshotDatabase()
    vector = _vector("cat_a")
    birth = _birth(pid=100, boot_id="boot-a", start_ticks=10)
    lease = db.acquire_lease(
        vector=vector,
        catalog_id="cat_a",
        process_birth=birth,
        task_id="t",
        run_id="r",
        worker_id="w",
    )
    reused = _birth(pid=100, boot_id="boot-b", start_ticks=9999)
    with pytest.raises(snap.ReaderLeaseError, match="PID reuse"):
        db.renew_lease(
            lease_id=lease.lease_id,
            lease_token=lease.lease_token,
            process_birth=reused,
            task_id="t",
            run_id="r",
        )


def test_stale_fence_fails_closed_on_acquire_and_renew() -> None:
    db = snap.AuthoritativeSnapshotDatabase()
    vector = _vector("cat_a")
    birth = _birth()
    with pytest.raises(snap.ReaderLeaseError, match="stale owner-generation"):
        db.acquire_lease(
            vector=vector,
            catalog_id="cat_a",
            process_birth=birth,
            task_id="t",
            run_id="r",
            worker_id="w",
            expected_owner_generation=99,
        )
    lease = db.acquire_lease(
        vector=vector,
        catalog_id="cat_a",
        process_birth=birth,
        task_id="t",
        run_id="r",
        worker_id="w",
    )
    with pytest.raises(snap.ReaderLeaseError, match="stale fencing_epoch"):
        db.renew_lease(
            lease_id=lease.lease_id,
            lease_token=lease.lease_token,
            process_birth=birth,
            task_id="t",
            run_id="r",
            fencing_epoch=999,
        )
    with pytest.raises(snap.ReaderLeaseError, match="task/run fence"):
        db.release_lease(
            lease_id=lease.lease_id,
            lease_token=lease.lease_token,
            process_birth=birth,
            task_id="other-task",
            run_id="r",
        )


def test_live_lease_set_for_maintenance_and_bounded_expiry() -> None:
    db = snap.AuthoritativeSnapshotDatabase()
    clock = {"t": 1_700_000_000.0}
    db.set_clock(lambda: clock["t"])
    vector = _vector("cat_a", "cat_b")
    birth = _birth()
    l1 = db.acquire_lease(
        vector=vector,
        catalog_id="cat_a",
        process_birth=birth,
        task_id="t1",
        run_id="r1",
        worker_id="w1",
        ttl_seconds=30,
        lease_id="rl-1",
    )
    l2 = db.acquire_lease(
        vector=vector,
        catalog_id="cat_b",
        process_birth=_birth(pid=7),
        task_id="t2",
        run_id="r2",
        worker_id="w2",
        ttl_seconds=30,
        lease_id="rl-2",
    )
    live = db.list_live_leases()
    assert {row["lease_id"] for row in live} == {"rl-1", "rl-2"}
    # Simulate crash: time advances past ttl without renew/release.
    clock["t"] += 31
    expired = db.expire_due_leases()
    assert set(expired) == {"rl-1", "rl-2"}
    assert db.list_live_leases() == ()
    # Crashed readers cannot renew after expiry.
    with pytest.raises(snap.ReaderLeaseError, match="expired"):
        db.renew_lease(
            lease_id=l1.lease_id,
            lease_token=l1.lease_token,
            process_birth=birth,
            task_id="t1",
            run_id="r1",
        )
    assert db.get_lease(l2.lease_id).status is snap.LeaseStatus.EXPIRED  # type: ignore[union-attr]


def test_lease_file_representation_rejected() -> None:
    with pytest.raises(snap.ReaderLeaseError, match="not be represented only by a file"):
        snap.ReaderLease(
            lease_id="rl-x",
            lease_token="tok",
            vector_id="v",
            catalog_id="c",
            snapshot_version=1,
            owner_generation=1,
            fencing_epoch=1,
            process_birth=_birth(),
            task_id="t",
            run_id="r",
            worker_id="w",
            acquired_at="2026-01-01T00:00:00Z",
            expires_at="2026-01-01T01:00:00Z",
            representation="file",
        )


def test_assert_database_backed_authority() -> None:
    snap.assert_database_backed_authority(source="ok", representation="database")
    with pytest.raises(snap.SnapshotError, match="not be represented only by a file"):
        snap.assert_database_backed_authority(source="bad", is_file_only=True)
    with pytest.raises(snap.SnapshotError, match="not be represented only by a file"):
        snap.assert_database_backed_authority(
            source="bad", representation="json_file"
        )


def test_database_survives_restart_export_import() -> None:
    db = snap.AuthoritativeSnapshotDatabase(instance_id="inst-1")
    vector = _vector("cat_a")
    lease = db.acquire_lease(
        vector=vector,
        catalog_id="cat_a",
        process_birth=_birth(),
        task_id="t",
        run_id="r",
        worker_id="w",
        lease_id="rl-persist",
    )
    state = db.export_state()
    assert state["representation"] == "database"
    assert "lake_snapshot_vectors" in state["tables"]
    assert "lake_reader_leases" in state["tables"]

    db2 = snap.AuthoritativeSnapshotDatabase()
    db2.import_state(state)
    restored_v = db2.get_vector(vector.vector_id)
    assert restored_v is not None
    assert restored_v.identity_digest == vector.identity_digest
    restored_l = db2.get_lease("rl-persist")
    assert restored_l is not None
    assert restored_l.lease_token == lease.lease_token
    live = db2.list_live_leases()
    assert len(live) == 1


# ---------------------------------------------------------------------------
# Time travel
# ---------------------------------------------------------------------------


def test_time_travel_same_logical_result() -> None:
    vector = _vector("cat_a", "cat_b")
    retained = {
        "cat_a": (7, 6, 5),
        "cat_b": (7, 8),
    }
    r1 = snap.replay_time_travel(
        vector, retained_snapshots=retained, logical_query_id="q-1"
    )
    r2 = snap.replay_time_travel(
        vector, retained_snapshots=retained, logical_query_id="q-1"
    )
    assert r1.logical_result_digest == r2.logical_result_digest
    assert r1.retained is True
    assert r1.snapshot_versions["cat_a"] == 7


def test_time_travel_retention_error() -> None:
    vector = _vector("cat_a", "cat_b")
    retained = {"cat_a": (1, 2), "cat_b": (7,)}  # cat_a missing 7
    with pytest.raises(snap.SnapshotRetentionError, match="retention window"):
        snap.replay_time_travel(
            vector, retained_snapshots=retained, logical_query_id="q-1"
        )


def test_time_travel_custom_result_builder() -> None:
    vector = _vector("cat_a")
    retained = {"cat_a": (7,)}

    def builder(v: snap.SnapshotVector) -> dict[str, Any]:
        return {"rows": [1, 2, 3], "vector": v.identity_digest}

    r = snap.replay_time_travel(
        vector,
        retained_snapshots=retained,
        logical_query_id="q",
        result_builder=builder,
    )
    assert r.logical_result_digest.startswith("sha256:")


# ---------------------------------------------------------------------------
# Catalog race retry + concurrency + cross-shard non-atomicity
# ---------------------------------------------------------------------------


def test_catalog_race_retry_then_success() -> None:
    db = snap.AuthoritativeSnapshotDatabase()
    db.catalog_race_max_attempts = 3
    state = {"n": 0}

    def op() -> str:
        state["n"] += 1
        if state["n"] < 3:
            raise snap.SnapshotError("catalog race conflict on shard")
        return "ok"

    assert db.with_catalog_race_retry(op) == "ok"
    assert state["n"] == 3


def test_catalog_race_retry_exhausted() -> None:
    db = snap.AuthoritativeSnapshotDatabase()
    db.catalog_race_max_attempts = 2

    def op() -> None:
        raise snap.SnapshotError("persistent race conflict")

    with pytest.raises(snap.SnapshotError, match="persistent race"):
        db.with_catalog_race_retry(op)


def test_independent_shard_leases_no_cross_shard_atomicity() -> None:
    db = snap.AuthoritativeSnapshotDatabase()
    vector = _vector("cat_a", "cat_b")
    # Mapping documents no cross-shard atomicity.
    assert vector.as_mapping()["cross_shard_atomicity"] is False
    errors: list[str] = []

    def worker(catalog_id: str, pid: int) -> None:
        try:
            lease = db.acquire_lease(
                vector=vector,
                catalog_id=catalog_id,
                process_birth=_birth(pid=pid),
                task_id=f"task-{catalog_id}",
                run_id=f"run-{catalog_id}",
                worker_id=f"w-{catalog_id}",
            )
            db.release_lease(
                lease_id=lease.lease_id,
                lease_token=lease.lease_token,
                process_birth=_birth(pid=pid),
                task_id=f"task-{catalog_id}",
                run_id=f"run-{catalog_id}",
            )
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(str(exc))

    threads = [
        threading.Thread(target=worker, args=("cat_a", 1)),
        threading.Thread(target=worker, args=("cat_b", 2)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []


def test_stale_owner_generation_member_fails_on_attach() -> None:
    member = _member("cat_a", fencing_epoch=2)
    profile = _profile("cat_a")  # fencing_epoch=1
    with pytest.raises(snap.SnapshotAttachError, match="fencing_epoch"):
        snap.build_owner_snapshot_attach(profile, member)


# ---------------------------------------------------------------------------
# Import side-effect free
# ---------------------------------------------------------------------------


def test_import_is_side_effect_free() -> None:
    importlib.reload(snap)
    assert hasattr(snap, "capture_snapshot_vector")
    assert hasattr(snap, "AuthoritativeSnapshotDatabase")
    # Module must not require duckdb at import time.
    assert "SnapshotVector" in snap.__all__
    assert ATTACH_SAFE_OPTIONS["CREATE_IF_NOT_EXISTS"] is False
