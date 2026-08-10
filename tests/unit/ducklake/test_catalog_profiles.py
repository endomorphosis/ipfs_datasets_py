"""Hermetic unit tests for DQK-085 catalog-shard, storage, and secret profiles.

Covers:

* one DuckDB metadata file per shard opened by exactly one identity-bound owner
* remote clients cannot open/mount/mutate the catalog file
* same-shard serialization and concurrent independent shards
* authority paths fail closed on NFS, SMB, object URLs, shared mounts
* active/passive takeover precondition package
* normalized allowlisted repository-independent paths
* DuckLake has no auth layer; trusted broker authorizes and injects one-use Quack caps
* least-privilege identities; object-delete IAM is separate and short-lived
* secrets never enter configuration projections
* non-bootstrap ATTACH safety flags; bootstrap/migration require separate auth

Never imports optional ``duckdb``, never LOADs extensions, never opens sockets.
"""

from __future__ import annotations

import builtins
import concurrent.futures
import importlib
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.ducklake import catalog as cat
from ipfs_datasets_py.ducklake import config as cfg
from ipfs_datasets_py.ducklake.capabilities import ATTACH_SAFE_OPTIONS


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

_AUTHORITY_ROOT = "/var/lib/ducklake/catalogs"
_PARQUET_ROOT = "/var/lib/ducklake/parquet"
_OBJECT_ROOT = "s3://lake-bucket/namespaces"
_DIGEST = "ab" * 32
_CMDLINE = "cd" * 32


def _mount_local(_path: str) -> str:
    return "ext4"


def _mount_nfs(_path: str) -> str:
    return "nfs4"


def _versioned_true(_path: str) -> bool:
    return True


def _storage(
    *,
    shard: str = "shard-a",
    catalog_path: str | None = None,
    companion_path: str | None = None,
    parquet_path: str | None = None,
    mount_probe=None,
    mounts_table=None,
    object_versioning_probe=None,
    parquet_roots: tuple[str, ...] | None = None,
    authority_roots: tuple[str, ...] | None = None,
) -> cfg.StorageProfile:
    return cfg.build_storage_profile(
        profile_id=f"storage:{shard}",
        authority_roots=authority_roots or (_AUTHORITY_ROOT,),
        parquet_roots=parquet_roots or (_PARQUET_ROOT, _OBJECT_ROOT),
        catalog_metadata_path=catalog_path
        or f"{_AUTHORITY_ROOT}/{shard}/catalog.duckdb",
        companion_registry_path=companion_path
        or f"{_AUTHORITY_ROOT}/{shard}/companion.duckdb",
        parquet_data_path=parquet_path
        or f"{_PARQUET_ROOT}/{shard}/data",
        parquet_namespace_id=f"ns:{shard}",
        parquet_staging_path=f"{_PARQUET_ROOT}/{shard}/staging",
        mount_probe=mount_probe or _mount_local,
        mounts_table=mounts_table,
        object_versioning_probe=object_versioning_probe or _versioned_true,
    )


def _secrets(shard: str = "shard-a") -> cfg.SecretProfile:
    return cfg.build_secret_profile(
        profile_id=f"secrets:{shard}",
        references={
            "quack_token": "vault://ducklake/quack-token",
            "object_write": "aws-sm://lake/object-write",
        },
        parquet_key_ref="vault://ducklake/parquet-key",
        catalog_key_ref="vault://ducklake/catalog-key",
        purposes={
            "quack_token": "quack_endpoint_token",
            "object_write": "object_store_write",
        },
    )


def _owner(shard: str = "shard-a", pid: int = 4242) -> cat.OwnerProcessIdentity:
    return cat.build_owner_process_identity(
        principal=f"owner-broker:{shard}",
        pid=pid,
        boot_id="boot-test-001",
        start_ticks=1000 + pid,
        cmdline_sha256=_CMDLINE,
    )


def _endpoint(shard: str = "shard-a", port: int = 19090) -> cat.QuackEndpointIdentity:
    return cat.build_quack_endpoint(
        endpoint_id=f"quack:{shard}",
        bind_address="127.0.0.1",
        port=port,
        token_reference_id="tokref:" + shard,
    )


def _profile(
    *,
    catalog_id: str = "catalog-main",
    shard: str = "shard-a",
    generation: int = 1,
    fencing_epoch: int = 1,
    pid: int = 4242,
    port: int = 19090,
    storage: cfg.StorageProfile | None = None,
) -> cat.CatalogShardProfile:
    return cat.build_catalog_shard_profile(
        catalog_id=catalog_id,
        shard_id=shard,
        storage=storage or _storage(shard=shard),
        secrets=_secrets(shard=shard),
        owner=_owner(shard=shard, pid=pid),
        endpoint=_endpoint(shard=shard, port=port),
        catalog_digest=_DIGEST,
        generation=generation,
        fencing_epoch=fencing_epoch,
        issued_at_unix=1_700_000_000,
    )


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_config_and_catalog_import_side_effect_free(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    for mod in (
        "ipfs_datasets_py.ducklake.catalog",
        "ipfs_datasets_py.ducklake.config",
    ):
        sys.modules.pop(mod, None)
    monkeypatch.setattr(builtins, "__import__", guarded)
    config_mod = importlib.import_module("ipfs_datasets_py.ducklake.config")
    catalog_mod = importlib.import_module("ipfs_datasets_py.ducklake.catalog")
    assert config_mod.STORAGE_PROFILE_SCHEMA.endswith("@1")
    assert catalog_mod.DUCKLAKE_HAS_AUTHORIZATION_LAYER is False
    assert dict(catalog_mod.ATTACH_SAFE_OPTIONS) == dict(ATTACH_SAFE_OPTIONS)
    monkeypatch.setattr(builtins, "__import__", real_import)


# ---------------------------------------------------------------------------
# Single owner per shard + remote cannot open
# ---------------------------------------------------------------------------


def test_shard_binds_one_metadata_file_and_one_owner() -> None:
    profile = _profile()
    assert profile.single_owner is True
    assert profile.catalog_metadata_path.endswith("/catalog.duckdb")
    assert profile.companion_registry_path.endswith("/companion.duckdb")
    assert profile.catalog_metadata_path != profile.companion_registry_path
    assert profile.owner_generation.generation == 1
    assert profile.quack_endpoint.endpoint_id == "quack:shard-a"
    assert profile.storage.parquet_namespace.lifecycle_managed_by_ducklake is True
    owner = profile.identities[cfg.IdentityRole.OWNER_BROKER]
    assert owner.may_open_catalog_file is True
    assert profile.owner_generation.owner.principal == owner.principal


def test_remote_clients_cannot_open_mount_or_mutate_catalog() -> None:
    profile = _profile()
    assert profile.remote_clients_open_catalog_file is False
    for role in (
        cfg.IdentityRole.READER,
        cfg.IdentityRole.WRITER,
        cfg.IdentityRole.MAINTAINER,
    ):
        for action in (
            "open",
            "mount",
            "network_mount",
            "copy_into_place",
            "mutate_file",
            "direct_attach",
            "replace_file",
        ):
            with pytest.raises(cat.RemoteCatalogAccessError):
                cat.assert_remote_cannot_open_catalog(
                    caller_role=role,
                    action=action,
                    identities=profile.identities,
                )
    # Owner broker may open.
    cat.assert_remote_cannot_open_catalog(
        caller_role=cfg.IdentityRole.OWNER_BROKER,
        action="open",
        identities=profile.identities,
    )


def test_plane_refuses_second_owner_without_takeover() -> None:
    plane = cat.CatalogShardPlane()
    first = _profile(pid=100)
    plane.register(first)
    second = _profile(pid=200)
    with pytest.raises(cat.CatalogOwnershipError, match="second owner"):
        plane.register(second)


def test_same_shard_serialized_independent_shards_concurrent() -> None:
    plane = cat.CatalogShardPlane()
    a = _profile(shard="shard-a", pid=1, port=19001)
    b = _profile(shard="shard-b", pid=2, port=19002)
    plane.register(a)
    plane.register(b)

    order: list[str] = []
    barrier = threading.Barrier(2)
    hold_a = threading.Event()
    entered_a = threading.Event()

    def work_a() -> str:
        def body() -> str:
            entered_a.set()
            order.append("a-enter")
            assert hold_a.wait(timeout=2)
            order.append("a-exit")
            return "a"

        return plane.serialize_same_shard(
            "catalog-main",
            "shard-a",
            body,
            caller_process_id=a.owner_generation.owner.process_id,
        )

    def work_a_blocked() -> str:
        barrier.wait(timeout=2)
        # Must not interleave with work_a on the same shard.
        def body() -> str:
            order.append("a2-run")
            return "a2"

        return plane.serialize_same_shard(
            "catalog-main",
            "shard-a",
            body,
            caller_process_id=a.owner_generation.owner.process_id,
        )

    def work_b() -> str:
        barrier.wait(timeout=2)

        def body() -> str:
            order.append("b-run")
            return "b"

        return plane.serialize_same_shard(
            "catalog-main",
            "shard-b",
            body,
            caller_process_id=b.owner_generation.owner.process_id,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        fa = pool.submit(work_a)
        assert entered_a.wait(timeout=2)
        fa2 = pool.submit(work_a_blocked)
        fb = pool.submit(work_b)
        # shard-b proceeds while shard-a is held
        assert fb.result(timeout=2) == "b"
        assert "b-run" in order
        assert "a2-run" not in order  # still blocked behind a
        hold_a.set()
        assert fa.result(timeout=2) == "a"
        assert fa2.result(timeout=2) == "a2"

    assert order.index("a-enter") < order.index("a-exit")
    assert order.index("a-exit") < order.index("a2-run")
    assert "b-run" in order


def test_non_owner_caller_cannot_hold_shard_lock() -> None:
    plane = cat.CatalogShardPlane()
    profile = _profile()
    plane.register(profile)
    with pytest.raises(cat.CatalogOwnershipError, match="not the fenced owner"):
        plane.serialize_same_shard(
            profile.catalog_id,
            profile.shard_id,
            lambda: None,
            caller_process_id="intruder",
        )


# ---------------------------------------------------------------------------
# Authority path fail-closed rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "s3://bucket/catalog.duckdb",
        "gs://bucket/catalog.duckdb",
        "nfs://server/export/catalog.duckdb",
        "smb://server/share/catalog.duckdb",
        "cifs://server/share/catalog.duckdb",
        "https://example.com/catalog.duckdb",
        "ipfs://bafyexample/catalog.duckdb",
        r"\\server\share\catalog.duckdb",
        "relative/catalog.duckdb",
        "file://remote-host/var/lib/catalog.duckdb",
    ],
)
def test_authority_paths_reject_network_and_object_urls(bad_path: str) -> None:
    allowlist = cfg.PathAllowlist(roots=(_AUTHORITY_ROOT,))
    with pytest.raises(cfg.AuthorityPathError):
        cfg.normalize_authority_path(
            bad_path,
            role=cfg.AuthorityFileRole.CATALOG_METADATA,
            allowlist=allowlist,
            mount_probe=_mount_local,
        )


def test_authority_path_rejects_nfs_mount() -> None:
    allowlist = cfg.PathAllowlist(roots=(_AUTHORITY_ROOT,))
    with pytest.raises(cfg.AuthorityPathError, match="nfs4"):
        cfg.normalize_authority_path(
            f"{_AUTHORITY_ROOT}/shard-a/catalog.duckdb",
            role=cfg.AuthorityFileRole.CATALOG_METADATA,
            allowlist=allowlist,
            mount_probe=_mount_nfs,
        )


def test_authority_path_rejects_smb_fstype_from_mounts_table() -> None:
    allowlist = cfg.PathAllowlist(roots=(_AUTHORITY_ROOT,))
    with pytest.raises(cfg.AuthorityPathError, match="cifs"):
        cfg.normalize_authority_path(
            f"{_AUTHORITY_ROOT}/shard-a/catalog.duckdb",
            role=cfg.AuthorityFileRole.CATALOG_METADATA,
            allowlist=allowlist,
            mounts_table=(("/var/lib/ducklake", "cifs"),),
        )


def test_authority_path_must_be_allowlisted_and_absolute() -> None:
    allowlist = cfg.PathAllowlist(roots=(_AUTHORITY_ROOT,))
    with pytest.raises(cfg.AuthorityPathError, match="outside the allowlisted"):
        cfg.normalize_authority_path(
            "/tmp/not-allowlisted/catalog.duckdb",
            role=cfg.AuthorityFileRole.CATALOG_METADATA,
            allowlist=allowlist,
            mount_probe=_mount_local,
        )


def test_companion_registry_also_requires_block_storage() -> None:
    with pytest.raises(cfg.AuthorityPathError):
        _storage(companion_path="s3://bucket/companion.duckdb")


def test_catalog_and_companion_must_be_distinct() -> None:
    path = f"{_AUTHORITY_ROOT}/shard-a/same.duckdb"
    with pytest.raises(cfg.AuthorityPathError, match="distinct"):
        _storage(catalog_path=path, companion_path=path)


def test_parquet_accepts_versioned_object_and_local_block() -> None:
    local = _storage(parquet_path=f"{_PARQUET_ROOT}/shard-a/data")
    assert (
        local.parquet_namespace.data_path.storage_class
        is cfg.ParquetStorageClass.LOCAL_BLOCK
    )
    obj = _storage(parquet_path=f"{_OBJECT_ROOT}/shard-a")
    assert (
        obj.parquet_namespace.data_path.storage_class
        is cfg.ParquetStorageClass.VERSIONED_OBJECT
    )
    assert obj.parquet_namespace.data_path.versioned is True


def test_parquet_rejects_unversioned_object_and_ipfs_data_path() -> None:
    with pytest.raises(cfg.CatalogConfigError, match="versioning"):
        _storage(
            parquet_path=f"{_OBJECT_ROOT}/shard-a",
            object_versioning_probe=lambda _p: False,
        )
    with pytest.raises(cfg.CatalogConfigError, match="provenance"):
        allowlist = cfg.PathAllowlist(roots=(_PARQUET_ROOT, _OBJECT_ROOT))
        cfg.normalize_parquet_path(
            "ipfs://bafySourceCid",
            allowlist=allowlist,
        )


def test_staging_must_sit_outside_data_path() -> None:
    with pytest.raises(cfg.CatalogConfigError, match="outside DATA_PATH"):
        data = cfg.normalize_parquet_path(
            f"{_PARQUET_ROOT}/shard-a/data",
            allowlist=cfg.PathAllowlist(roots=(_PARQUET_ROOT,)),
        )
        staging = cfg.normalize_parquet_path(
            f"{_PARQUET_ROOT}/shard-a/data/staging",
            allowlist=cfg.PathAllowlist(roots=(_PARQUET_ROOT,)),
        )
        cfg.ParquetNamespaceProfile(
            namespace_id="ns",
            data_path=data,
            staging_path=staging,
        )


def test_paths_normalized_collapse_dot_segments() -> None:
    allowlist = cfg.PathAllowlist(roots=(_AUTHORITY_ROOT,))
    path = cfg.normalize_authority_path(
        f"{_AUTHORITY_ROOT}/shard-a/./nested/../catalog.duckdb",
        role=cfg.AuthorityFileRole.CATALOG_METADATA,
        allowlist=allowlist,
        mount_probe=_mount_local,
    )
    assert path.path == f"{_AUTHORITY_ROOT}/shard-a/catalog.duckdb"
    assert ".." not in path.path
    assert "/./" not in path.path


# ---------------------------------------------------------------------------
# Active/passive takeover
# ---------------------------------------------------------------------------


def _prior_and_successor(
    profile: cat.CatalogShardProfile,
) -> tuple[cat.OwnerGenerationReceipt, cat.OwnerGenerationReceipt]:
    prior_owner = profile.owner_generation.owner
    # Prior must have stopped admission.
    prior = cat.OwnerGenerationReceipt(
        receipt_id=profile.owner_generation.receipt_id,
        catalog_id=profile.catalog_id,
        shard_id=profile.shard_id,
        generation=profile.owner_generation.generation,
        fencing_epoch=profile.owner_generation.fencing_epoch,
        owner=prior_owner,
        endpoint=profile.quack_endpoint,
        catalog_digest=profile.owner_generation.catalog_digest,
        lease_expires_at_unix=profile.owner_generation.lease_expires_at_unix,
        admission_open=False,
        issued_at_unix=profile.owner_generation.issued_at_unix,
    )
    successor_owner = cat.build_owner_process_identity(
        principal=f"owner-broker:{profile.shard_id}",
        pid=prior_owner.pid + 1000,
        boot_id="boot-test-002",
        start_ticks=prior_owner.start_ticks + 5000,
        cmdline_sha256="ef" * 32,
    )
    successor_endpoint = cat.build_quack_endpoint(
        endpoint_id=f"quack:{profile.shard_id}:gen2",
        port=profile.quack_endpoint.port + 1,
        token_reference_id="tokref-rotated",
    )
    successor = cat.build_owner_generation_receipt(
        catalog_id=profile.catalog_id,
        shard_id=profile.shard_id,
        generation=prior.generation + 1,
        fencing_epoch=prior.fencing_epoch + 1,
        owner=successor_owner,
        endpoint=successor_endpoint,
        catalog_digest=_DIGEST,
        issued_at_unix=prior.issued_at_unix + 10,
    )
    return prior, successor


def _complete_takeover_evidence(
    profile: cat.CatalogShardProfile,
    **overrides: Any,
) -> cat.TakeoverEvidence:
    prior, successor = _prior_and_successor(profile)
    payload: dict[str, Any] = {
        "prior_generation_receipt": prior,
        "successor_generation_receipt": successor,
        "prior_stopped_admission": True,
        "prior_process_dead_or_fenced": True,
        "endpoint_token_revoked": True,
        "storage_capabilities_expired": True,
        "all_handles_closed": True,
        "catalog_digest_matches": True,
        "catalog_generation_matches": True,
        "native_file_lock": cat.NativeFileLockEvidence(
            path=profile.catalog_metadata_path,
            acquired=True,
            locker_process_id=successor.owner.process_id,
            acquisition_unix=prior.issued_at_unix + 11,
        ),
    }
    payload.update(overrides)
    return cat.TakeoverEvidence(**payload)


def test_takeover_requires_full_precondition_package() -> None:
    profile = _profile()
    evidence = _complete_takeover_evidence(profile)
    result = dict(cat.evaluate_takeover(evidence))
    assert result["allowed"] is True
    assert result["successor_generation"] == 2

    # Each missing precondition fails closed.
    failures = [
        {"prior_stopped_admission": False},
        {"prior_process_dead_or_fenced": False},
        {"endpoint_token_revoked": False},
        {"storage_capabilities_expired": False},
        {"all_handles_closed": False},
        {"catalog_digest_matches": False},
        {"catalog_generation_matches": False},
    ]
    for override in failures:
        with pytest.raises(cat.TakeoverError):
            cat.evaluate_takeover(_complete_takeover_evidence(profile, **override))


def test_takeover_requires_native_file_lock_by_successor() -> None:
    profile = _profile()
    prior, successor = _prior_and_successor(profile)
    with pytest.raises(cat.TakeoverError, match="file lock"):
        cat.NativeFileLockEvidence(
            path=profile.catalog_metadata_path,
            acquired=False,
            locker_process_id=successor.owner.process_id,
            acquisition_unix=1,
        )
    bad_lock = cat.NativeFileLockEvidence(
        path=profile.catalog_metadata_path,
        acquired=True,
        locker_process_id="someone-else",
        acquisition_unix=1,
    )
    with pytest.raises(cat.TakeoverError, match="file lock must be held by the successor"):
        cat.evaluate_takeover(
            _complete_takeover_evidence(profile, native_file_lock=bad_lock)
        )


def test_plane_transfer_ownership_updates_owner() -> None:
    plane = cat.CatalogShardPlane()
    profile = _profile()
    plane.register(profile)
    evidence = _complete_takeover_evidence(profile)
    updated = plane.transfer_ownership(evidence)
    assert updated.owner_generation.generation == 2
    assert (
        plane.owner_process_id(profile.catalog_id, profile.shard_id)
        == evidence.successor_generation_receipt.owner.process_id
    )


# ---------------------------------------------------------------------------
# Broker authorization, one-use Quack capability, no DuckLake roles
# ---------------------------------------------------------------------------


def test_ducklake_has_no_authorization_layer() -> None:
    assert cat.DUCKLAKE_HAS_AUTHORIZATION_LAYER is False
    profile = _profile()
    assert profile.ducklake_authorization_layer is False
    broker = profile.make_broker()
    assert broker.ducklake_authorization_layer is False


def test_broker_authorizes_and_injects_one_use_quack_capability() -> None:
    profile = _profile()
    broker = profile.make_broker()
    auth = dict(
        broker.authorize(
            operation=cat.PrivilegedOperation.SNAPSHOT_READ,
            caller_role=cfg.IdentityRole.READER,
            caller_principal="reader:shard-a",
            caller_process_id="worker-1",
            resource="snapshot:1",
            nonce="nonce-1",
            now_unix=1_700_000_100,
        )
    )
    assert auth["broker_authorized"] is True
    assert auth["ducklake_authorized"] is False

    cap = broker.inject_one_use_quack_capability(
        worker_principal="reader:shard-a",
        worker_process_id="worker-1",
        worker_role=cfg.IdentityRole.READER,
        operation=cat.PrivilegedOperation.SNAPSHOT_READ,
        authorization=auth,
        now_unix=1_700_000_100,
    )
    projection = dict(cap.as_mapping())
    assert "material" not in projection
    assert projection["capability_id"].startswith("q1:")
    material = broker.consume_quack_capability(cap, now_unix=1_700_000_100)
    assert isinstance(material, str) and len(material) > 10
    with pytest.raises(cat.CatalogShardError, match="already consumed"):
        broker.consume_quack_capability(cap, now_unix=1_700_000_100)


def test_writer_cannot_self_authorize_object_delete_iam() -> None:
    profile = _profile()
    broker = profile.make_broker()
    with pytest.raises(cat.CatalogShardError, match="not authorized"):
        broker.authorize(
            operation=cat.PrivilegedOperation.OBJECT_DELETE,
            caller_role=cfg.IdentityRole.WRITER,
            caller_principal="writer:shard-a",
            caller_process_id="w1",
            resource="s3://lake-bucket/namespaces/shard-a",
            nonce="n-del",
            now_unix=1_700_000_100,
        )


def test_maintainer_object_delete_requires_separate_short_lived_iam() -> None:
    profile = _profile()
    broker = profile.make_broker()
    auth = dict(
        broker.authorize(
            operation=cat.PrivilegedOperation.OBJECT_DELETE,
            caller_role=cfg.IdentityRole.MAINTAINER,
            caller_principal="maintainer:shard-a",
            caller_process_id="m1",
            resource="s3://lake-bucket/namespaces/shard-a",
            nonce="n-del-ok",
            now_unix=1_700_000_100,
        )
    )
    iam = broker.mint_object_delete_iam(
        caller_role=cfg.IdentityRole.MAINTAINER,
        authorization=auth,
        resource_prefix=f"{_OBJECT_ROOT}/shard-a",
        ttl_seconds=120,
    )
    assert iam.kind == cfg.OBJECT_DELETE_IAM_KIND
    assert iam.ttl_seconds == 120
    assert iam.ttl_seconds <= 3600
    # Readers/writers are not eligible.
    reader = profile.identities[cfg.IdentityRole.READER]
    writer = profile.identities[cfg.IdentityRole.WRITER]
    assert reader.may_receive_object_delete_iam is False
    assert writer.may_receive_object_delete_iam is False
    assert cfg.ObjectCapabilityKind.DELETE not in reader.object_capabilities
    assert cfg.ObjectCapabilityKind.DELETE not in writer.object_capabilities


def test_least_privilege_identity_matrix() -> None:
    profiles = cfg.build_identity_profiles(
        shard_id="shard-a", object_prefix=f"{_OBJECT_ROOT}/shard-a"
    )
    assert set(profiles) == {
        cfg.IdentityRole.READER,
        cfg.IdentityRole.WRITER,
        cfg.IdentityRole.MAINTAINER,
        cfg.IdentityRole.OWNER_BROKER,
    }
    assert profiles[cfg.IdentityRole.READER].may_open_catalog_file is False
    assert profiles[cfg.IdentityRole.WRITER].may_open_catalog_file is False
    assert profiles[cfg.IdentityRole.MAINTAINER].may_open_catalog_file is False
    assert profiles[cfg.IdentityRole.OWNER_BROKER].may_open_catalog_file is True
    for role in (
        cfg.IdentityRole.READER,
        cfg.IdentityRole.WRITER,
        cfg.IdentityRole.MAINTAINER,
        cfg.IdentityRole.OWNER_BROKER,
    ):
        assert profiles[role].may_receive_reusable_quack_token is False


def test_quack_capability_projection_has_no_secret_material() -> None:
    profile = _profile()
    broker = profile.make_broker()
    auth = dict(
        broker.authorize(
            operation=cat.PrivilegedOperation.INGEST_REGISTER,
            caller_role=cfg.IdentityRole.WRITER,
            caller_principal="writer:shard-a",
            caller_process_id="w1",
            resource="dataset:x",
            nonce="n-ing",
            now_unix=1_700_000_100,
        )
    )
    cap = broker.inject_one_use_quack_capability(
        worker_principal="writer:shard-a",
        worker_process_id="w1",
        worker_role=cfg.IdentityRole.WRITER,
        operation=cat.PrivilegedOperation.INGEST_REGISTER,
        authorization=auth,
        now_unix=1_700_000_100,
    )
    cfg.assert_no_secret_material(dict(cap.as_mapping()))


# ---------------------------------------------------------------------------
# Secrets never enter projections
# ---------------------------------------------------------------------------


def test_secret_profile_stores_references_only() -> None:
    secrets = _secrets()
    mapping = dict(secrets.as_mapping())
    for ref in mapping["references"].values():
        assert ref["kind"] == "secret_reference"
        assert "vault://" not in str(ref)
        assert "reference_id" in ref
    assert mapping["encryption"]["parquet_key"]["kind"] == "encryption_key_reference"
    assert "vault://" not in str(mapping["encryption"])


def test_project_shard_profile_redacts_secrets() -> None:
    profile = _profile()
    projection = dict(cat.project_shard_profile(profile))
    text = str(projection)
    assert "vault://" not in text
    assert "password" not in text.lower() or projection.get("secrets") is not None
    cfg.assert_no_secret_material(projection)
    # Token reference ids only — no raw tokens.
    assert "tokref" in str(projection["extra"]["quack_endpoint"])


def test_assert_no_secret_material_catches_passwords_and_keys() -> None:
    with pytest.raises(cfg.SecretMaterialError):
        cfg.assert_no_secret_material({"password": "s3cr3t-value-here"})
    with pytest.raises(cfg.SecretMaterialError):
        cfg.assert_no_secret_material(
            {"note": "-----BEGIN PRIVATE KEY-----\nMIIE\n-----END PRIVATE KEY-----"}
        )
    with pytest.raises(cfg.SecretMaterialError):
        cfg.assert_no_secret_material({"auth": "Bearer abcdefghijklmnopqrstuvwxyz012345"})
    with pytest.raises(cfg.SecretMaterialError):
        cfg.assert_no_secret_material({"key": "AKIAIOSFODNN7EXAMPLE"})


def test_secret_reference_rejects_embedded_material() -> None:
    with pytest.raises(cfg.SecretMaterialError):
        cfg.SecretReference(
            reference="vault://path?password=hunter2",
            purpose="quack_token",
        )
    with pytest.raises(cfg.CatalogConfigError):
        cfg.SecretReference(reference="not-a-uri", purpose="x")


def test_encryption_defaults_required_before_ingest() -> None:
    with pytest.raises(cfg.CatalogConfigError, match="before first ingest"):
        cfg.EncryptionDefaults(
            enabled=False,
            parquet_key=None,
            catalog_key=None,
            require_before_ingest=True,
        )


# ---------------------------------------------------------------------------
# ATTACH safety contract
# ---------------------------------------------------------------------------


def test_runtime_attach_forces_safe_options() -> None:
    options = cat.build_attach_options(cat.AttachMode.RUNTIME)
    assert options.create_if_not_exists is False
    assert options.override_data_path is False
    assert options.automatic_migration is False
    assert dict(options.as_duckdb_options) == {
        "CREATE_IF_NOT_EXISTS": False,
        "OVERRIDE_DATA_PATH": False,
        "AUTOMATIC_MIGRATION": False,
    }
    assert dict(options.as_duckdb_options) == dict(ATTACH_SAFE_OPTIONS)
    inspection = dict(cat.inspect_attach_options(options))
    assert inspection["is_safe"] is True
    assert inspection["authorized_privileged"] is False


def test_runtime_attach_rejects_non_safe_flags() -> None:
    with pytest.raises(cat.CatalogShardError, match="runtime ATTACH"):
        cat.AttachOptions(
            mode=cat.AttachMode.RUNTIME,
            create_if_not_exists=True,
            override_data_path=False,
            automatic_migration=False,
        )


def test_bootstrap_and_migration_require_separate_authorization() -> None:
    profile = _profile()
    broker = profile.make_broker()
    with pytest.raises(cat.AttachAuthorizationError):
        cat.build_attach_options(
            cat.AttachMode.BOOTSTRAP,
            create_if_not_exists=True,
        )
    with pytest.raises(cat.AttachAuthorizationError):
        cat.build_attach_options(
            cat.AttachMode.MIGRATION,
            automatic_migration=True,
        )

    boot_auth = broker.issue_attach_authorization(
        mode=cat.AttachMode.BOOTSTRAP,
        caller_principal="owner-broker:shard-a",
        nonce="boot-1",
        now_unix=1_700_000_100,
    )
    boot = cat.build_attach_options(
        cat.AttachMode.BOOTSTRAP,
        create_if_not_exists=True,
        override_data_path=False,
        automatic_migration=False,
        authorization=boot_auth,
        now_unix=1_700_000_100,
    )
    assert boot.create_if_not_exists is True
    inspection = dict(cat.inspect_attach_options(boot))
    assert inspection["authorized_privileged"] is True
    assert inspection["is_safe"] is False

    mig_auth = broker.issue_attach_authorization(
        mode=cat.AttachMode.MIGRATION,
        caller_principal="owner-broker:shard-a",
        nonce="mig-1",
        now_unix=1_700_000_100,
    )
    mig = cat.build_attach_options(
        cat.AttachMode.MIGRATION,
        create_if_not_exists=False,
        override_data_path=True,
        automatic_migration=True,
        authorization=mig_auth,
        now_unix=1_700_000_100,
    )
    assert mig.override_data_path is True
    assert mig.automatic_migration is True


def test_inspect_rejects_unsafe_non_authorized_attach_mapping() -> None:
    with pytest.raises(cat.CatalogShardError, match="CREATE_IF_NOT_EXISTS"):
        cat.inspect_attach_options(
            {
                "mode": "runtime",
                "CREATE_IF_NOT_EXISTS": True,
                "OVERRIDE_DATA_PATH": False,
                "AUTOMATIC_MIGRATION": False,
            }
        )


def test_profile_runtime_attach_options_are_safe() -> None:
    profile = _profile()
    options = profile.runtime_attach_options()
    assert dict(options.as_duckdb_options) == dict(ATTACH_SAFE_OPTIONS)
    # Prove every non-bootstrap path through the profile is safe.
    for mode in (cat.AttachMode.RUNTIME,):
        opts = cat.build_attach_options(mode)
        result = dict(cat.inspect_attach_options(opts, require_runtime_safe=True))
        assert result["CREATE_IF_NOT_EXISTS"] is False
        assert result["OVERRIDE_DATA_PATH"] is False
        assert result["AUTOMATIC_MIGRATION"] is False


def test_expired_bootstrap_authorization_fails_closed() -> None:
    profile = _profile()
    broker = profile.make_broker()
    auth = broker.issue_attach_authorization(
        mode=cat.AttachMode.BOOTSTRAP,
        caller_principal="owner-broker:shard-a",
        nonce="boot-exp",
        now_unix=1_700_000_000,
        ttl_seconds=10,
    )
    with pytest.raises(cat.AttachAuthorizationError, match="expired"):
        cat.build_attach_options(
            cat.AttachMode.BOOTSTRAP,
            create_if_not_exists=True,
            authorization=auth,
            now_unix=1_700_000_100,
        )


# ---------------------------------------------------------------------------
# Aggregate profile invariants
# ---------------------------------------------------------------------------


def test_catalog_shard_profile_mapping_is_versioned() -> None:
    profile = _profile()
    mapping = dict(profile.as_mapping())
    assert mapping["schema"] == cat.CATALOG_SHARD_PROFILE_SCHEMA
    assert mapping["single_owner"] is True
    assert mapping["same_shard_serialized"] is True
    assert mapping["independent_shards_concurrent"] is True
    assert mapping["remote_clients_open_catalog_file"] is False
    assert mapping["ducklake_authorization_layer"] is False
    cfg.assert_no_secret_material(mapping)


def test_refuses_profile_that_enables_remote_catalog_open() -> None:
    base = _profile()
    with pytest.raises(cat.RemoteCatalogAccessError):
        cat.CatalogShardProfile(
            schema=cat.CATALOG_SHARD_PROFILE_SCHEMA,
            catalog_id=base.catalog_id,
            shard_id=base.shard_id,
            storage=base.storage,
            secrets=base.secrets,
            identities=base.identities,
            owner_generation=base.owner_generation,
            quack_endpoint=base.quack_endpoint,
            remote_clients_open_catalog_file=True,
        )


def test_refuses_multi_owner_flag() -> None:
    base = _profile()
    with pytest.raises(cat.CatalogOwnershipError, match="exactly one"):
        cat.CatalogShardProfile(
            schema=cat.CATALOG_SHARD_PROFILE_SCHEMA,
            catalog_id=base.catalog_id,
            shard_id=base.shard_id,
            storage=base.storage,
            secrets=base.secrets,
            identities=base.identities,
            owner_generation=base.owner_generation,
            quack_endpoint=base.quack_endpoint,
            single_owner=False,
        )


def test_attach_safe_options_align_with_capabilities_module() -> None:
    assert cat.ATTACH_SAFE_OPTIONS["CREATE_IF_NOT_EXISTS"] is False
    assert cat.ATTACH_SAFE_OPTIONS["OVERRIDE_DATA_PATH"] is False
    assert cat.ATTACH_SAFE_OPTIONS["AUTOMATIC_MIGRATION"] is False
    assert set(cat.ATTACH_OPTION_KEYS) == set(ATTACH_SAFE_OPTIONS.keys())
