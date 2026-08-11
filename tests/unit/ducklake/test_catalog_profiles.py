"""Hermetic unit tests for DQK-085 DuckDB + Quack catalog-shard profiles.

All tests use pure in-memory fixtures. The suite never imports optional
``duckdb``, never LOADs extensions, never ATTACHes a live catalog, and never
opens network sockets. It covers:

* one metadata file + one owner process per catalog shard
* remote clients denied open/mount/mutate of the catalog file
* same-shard serialization and independent-shard concurrency
* local/attached block storage only for live catalog and companion registry
* NFS, SMB, object URLs, and shared filesystem authority paths fail closed
* active/passive takeover preconditions
* normalized allowlisted paths and lifecycle-managed Parquet namespaces
* DuckLake supplies no authorization layer; trusted broker + one-use capability
* least-privilege reader/writer/maintainer/owner-broker identities
* separate short-lived object-delete IAM
* secrets never enter configuration projections
* non-bootstrap ATTACH forces CREATE_IF_NOT_EXISTS/OVERRIDE_DATA_PATH/
  AUTOMATIC_MIGRATION = false
"""

from __future__ import annotations

import importlib
import sys
import threading
import time
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

from ipfs_datasets_py.ducklake import catalog as cat
from ipfs_datasets_py.ducklake import config as cfg
from ipfs_datasets_py.ducklake.capabilities import ATTACH_SAFE_OPTIONS


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

_DIGEST_A = "sha256:" + ("ab" * 32)
_DIGEST_B = "sha256:" + ("cd" * 32)
_CMDLINE = "sha256:" + ("11" * 32)

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


def _owner_lease(**overrides: Any) -> cfg.OwnerLeaseBinding:
    payload: dict[str, Any] = {
        "lease_id": "lease-catalog-a-1",
        "owner_generation": 1,
        "fencing_epoch": 1,
        "process_birth": _birth(),
        "endpoint_identity": "quacks://127.0.0.1:19001/catalog_a",
        "os_identity": "ducklake_catalog_a_owner",
    }
    payload.update(overrides)
    if "process_birth" in overrides and isinstance(overrides["process_birth"], dict):
        payload["process_birth"] = _birth(**overrides["process_birth"])
    return cfg.OwnerLeaseBinding(**payload)


def _endpoint(**overrides: Any) -> cfg.QuackEndpointProfile:
    payload = {
        "host": "127.0.0.1",
        "port": 19001,
        "database": "catalog_a",
        "use_tls": True,
    }
    payload.update(overrides)
    return cfg.QuackEndpointProfile(**payload)


def _delete_iam() -> cfg.ObjectDeleteIamCapability:
    return cfg.ObjectDeleteIamCapability(
        capability_ref=cfg.ExternalSecretReference(
            ref_id="vault:iam/object-delete/catalog-a",
            purpose="object_delete",
            provider="vault",
        ),
        max_ttl_seconds=120,
    )


def _parquet(
    *,
    storage_kind: cfg.ParquetStorageKind | str | None = None,
    **overrides: Any,
) -> cfg.ParquetNamespace:
    # Resolve defaults at call time so importlib.reload of config stays safe.
    if storage_kind is None:
        storage_kind = cfg.ParquetStorageKind.LOCAL
    if storage_kind == cfg.ParquetStorageKind.LOCAL or storage_kind == "local":
        payload: dict[str, Any] = {
            "data_path": "/var/lib/ducklake/data/catalog_a",
            "storage_kind": storage_kind,
            "namespace_id": "catalog_a_ns",
            "staging_path": "/var/lib/ducklake/staging/catalog_a",
            "allowlist": _ALLOWLIST,
            "provenance_cid_roots": ("bafybeigdyrzt",),
        }
    else:
        payload = {
            "data_path": "s3://lake-bucket/namespaces/catalog_a",
            "storage_kind": storage_kind,
            "namespace_id": "catalog_a_ns",
            "object_store": cfg.ObjectStoreNamespace(
                endpoint="https://s3.example.invalid",
                region="us-east-1",
                bucket_or_root="lake-bucket",
                versioning_required=True,
                delete_iam=_delete_iam(),
            ),
            "provenance_cid_roots": ("bafybeigdyrzt",),
        }
    payload.update(overrides)
    return cfg.ParquetNamespace(**payload)


def _secrets(**overrides: Any) -> cfg.SecretProfile:
    payload: dict[str, Any] = {
        "quack_capability_ref": cfg.ExternalSecretReference(
            ref_id="vault:quack/catalog-a/broker",
            purpose="quack_capability",
            provider="vault",
        ),
        "object_read_ref": cfg.ExternalSecretReference(
            ref_id="vault:obj/catalog-a/read",
            purpose="object_read",
        ),
        "object_write_ref": cfg.ExternalSecretReference(
            ref_id="vault:obj/catalog-a/write",
            purpose="object_write",
        ),
        "object_delete_ref": cfg.ExternalSecretReference(
            ref_id="vault:obj/catalog-a/delete",
            purpose="object_delete",
        ),
        "catalog_encryption_key_ref": cfg.ExternalSecretReference(
            ref_id="kms:key/catalog-a",
            purpose="encryption_key",
            provider="kms",
        ),
        "signing_key_ref": cfg.ExternalSecretReference(
            ref_id="kms:key/signing-a",
            purpose="signing_key",
            provider="kms",
        ),
    }
    payload.update(overrides)
    return cfg.SecretProfile(**payload)


def _profile(
    catalog_id: str = "catalog_a",
    *,
    port: int = 19001,
    **overrides: Any,
) -> cfg.CatalogShardProfile:
    catalog_path = overrides.pop(
        "catalog_path", f"/var/lib/ducklake/catalogs/{catalog_id}.duckdb"
    )
    registry_path = overrides.pop(
        "registry_path", f"/var/lib/ducklake/registries/{catalog_id}_registry.duckdb"
    )
    payload: dict[str, Any] = {
        "catalog_id": catalog_id,
        "catalog_metadata": cfg.AuthorityDatabasePath(
            path=catalog_path,
            storage_kind=cfg.AuthorityStorageKind.LOCAL_BLOCK,
            role="catalog",
            allowlist=_ALLOWLIST,
        ),
        "companion_registry": cfg.AuthorityDatabasePath(
            path=registry_path,
            storage_kind=cfg.AuthorityStorageKind.LOCAL_BLOCK,
            role="companion_registry",
            allowlist=_ALLOWLIST,
        ),
        "quack_endpoint": _endpoint(
            port=port, database=catalog_id, host="127.0.0.1"
        ),
        "owner_lease": _owner_lease(
            lease_id=f"lease-{catalog_id}-1",
            endpoint_identity=f"quacks://127.0.0.1:{port}/{catalog_id}",
            os_identity=f"ducklake_{catalog_id}_owner",
        ),
        "parquet_namespace": _parquet(
            namespace_id=f"{catalog_id}_ns",
            data_path=f"/var/lib/ducklake/data/{catalog_id}",
            staging_path=f"/var/lib/ducklake/staging/{catalog_id}",
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


def _worker(
    *,
    worker_id: str = "worker-1",
    role: cfg.CatalogIdentityRole | str | None = None,
    trusted: bool = True,
) -> cat.WorkerIdentity:
    if role is None:
        role = cfg.CatalogIdentityRole.WRITER
    return cat.WorkerIdentity(
        worker_id=worker_id,
        role=role,
        process_birth={
            "pid": 99,
            "boot_id": "boot-worker",
            "start_ticks": 50,
            "cmdline_sha256": _CMDLINE,
        },
        trusted=trusted,
    )


def _receipt(
    *,
    catalog_id: str = "catalog_a",
    owner_generation: int = 1,
    catalog_path: str = "/var/lib/ducklake/catalogs/catalog_a.duckdb",
    catalog_digest: str = _DIGEST_A,
) -> cat.OwnerGenerationReceipt:
    return cat.OwnerGenerationReceipt(
        receipt_id=f"ogr-{catalog_id}-{owner_generation}",
        catalog_id=catalog_id,
        owner_generation=owner_generation,
        fencing_epoch=owner_generation,
        catalog_digest=catalog_digest,
        catalog_path=catalog_path,
        companion_registry_digest=_DIGEST_B,
        endpoint_identity=f"quacks://127.0.0.1:19001/{catalog_id}",
        process_birth=dict(_birth().as_mapping()),
    )


def _predecessor(
    *,
    owner_generation: int = 1,
    **overrides: Any,
) -> cat.PredecessorFenceEvidence:
    payload = {
        "admission_stopped": True,
        "process_dead_or_fenced": True,
        "endpoint_token_revoked": True,
        "storage_capabilities_expired": True,
        "all_handles_closed": True,
        "prior_owner_generation": owner_generation,
        "prior_fencing_epoch": owner_generation,
    }
    payload.update(overrides)
    return cat.PredecessorFenceEvidence(**payload)


def _takeover(
    *,
    owner_generation: int = 1,
    successor: int = 2,
    lock: cat.NativeFileLockStatus | str | None = None,
    **overrides: Any,
) -> cat.TakeoverPreconditions:
    if lock is None:
        lock = cat.NativeFileLockStatus.ACQUIRED
    payload: dict[str, Any] = {
        "durable_owner_generation_receipt": _receipt(owner_generation=owner_generation),
        "predecessor": _predecessor(owner_generation=owner_generation),
        "expected_catalog_digest": _DIGEST_A,
        "expected_owner_generation": owner_generation,
        "native_file_lock": lock,
        "successor_owner_generation": successor,
    }
    payload.update(overrides)
    return cat.TakeoverPreconditions(**payload)


# ---------------------------------------------------------------------------
# Import inertness
# ---------------------------------------------------------------------------


def test_config_and_catalog_import_are_side_effect_free() -> None:
    assert "duckdb" not in sys.modules or sys.modules["duckdb"] is not None
    # Re-import must not pull duckdb as a hard dependency of these modules.
    importlib.reload(cfg)
    importlib.reload(cat)
    # The modules themselves must not import duckdb at module level.
    assert "duckdb" not in getattr(cfg, "__dict__", {})
    assert "duckdb" not in getattr(cat, "__dict__", {})


# ---------------------------------------------------------------------------
# Authority path policy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "nfs://filer/export/catalog.duckdb",
        "smb://fileserver/share/catalog.duckdb",
        "cifs://fileserver/share/catalog.duckdb",
        "s3://bucket/catalog.duckdb",
        "gs://bucket/catalog.duckdb",
        "https://example.com/catalog.duckdb",
        "ipfs://bafybeiabc/catalog.duckdb",
        "ipld://bafybeiabc",
        r"\\fileserver\share\catalog.duckdb",
        "//fileserver/share/catalog.duckdb",
        "relative/catalog.duckdb",
        "catalog.duckdb",
        "/",
    ],
)
def test_authority_paths_reject_nfs_smb_object_urls_and_relative(path: str) -> None:
    with pytest.raises(cfg.PathPolicyError):
        cfg.normalize_authority_path(path)


def test_authority_path_accepts_local_absolute_and_normalizes() -> None:
    assert (
        cfg.normalize_authority_path("/var/lib/ducklake/./catalogs/a.duckdb")
        == "/var/lib/ducklake/catalogs/a.duckdb"
    )
    assert (
        cfg.normalize_authority_path("/var/lib/ducklake/catalogs/../catalogs/a.duckdb")
        == "/var/lib/ducklake/catalogs/a.duckdb"
    )


def test_authority_path_allowlist_enforced() -> None:
    with pytest.raises(cfg.PathPolicyError, match="outside the allowlisted"):
        cfg.validate_path_under_allowlist(
            "/etc/secret.duckdb",
            _ALLOWLIST,
            field_name="catalog_path",
        )
    assert cfg.validate_path_under_allowlist(
        "/var/lib/ducklake/catalogs/a.duckdb",
        _ALLOWLIST,
    ).endswith("a.duckdb")


def test_shared_filesystem_probe_fails_closed() -> None:
    def probe(_path: str) -> str:
        return "nfs4"

    with pytest.raises(cfg.PathPolicyError, match="filesystem type"):
        cfg.assert_authority_path_admitted(
            "/var/lib/ducklake/catalogs/a.duckdb",
            allowlist=_ALLOWLIST,
            filesystem_type_probe=probe,
        )


def test_attached_block_authority_path_admitted() -> None:
    path = cfg.AuthorityDatabasePath(
        path="/var/lib/ducklake/catalogs/a.duckdb",
        storage_kind=cfg.AuthorityStorageKind.ATTACHED_BLOCK,
        role="catalog",
        allowlist=_ALLOWLIST,
    )
    assert path.storage_kind is cfg.AuthorityStorageKind.ATTACHED_BLOCK


# ---------------------------------------------------------------------------
# Parquet namespace / DATA_PATH
# ---------------------------------------------------------------------------


def test_parquet_local_namespace_outside_repo_and_lifecycle_managed() -> None:
    ns = _parquet()
    assert ns.data_path.startswith("/var/lib/ducklake/data/")
    assert ns.staging_path is not None
    assert not ns.staging_path.startswith(ns.data_path.rstrip("/") + "/")
    mapping = ns.as_mapping()
    assert mapping["lifecycle_managed_by"] == "ducklake"
    assert mapping["provenance_cid_roots"] == ["bafybeigdyrzt"]


def test_parquet_staging_inside_data_path_rejected() -> None:
    with pytest.raises(cfg.CatalogProfileError, match="outside DATA_PATH"):
        _parquet(staging_path="/var/lib/ducklake/data/catalog_a/staging")


def test_parquet_versioned_object_namespace() -> None:
    ns = _parquet(storage_kind=cfg.ParquetStorageKind.VERSIONED_OBJECT)
    assert ns.data_path.startswith("s3://")
    assert ns.object_store is not None
    assert ns.object_store.versioning_required is True
    assert ns.object_store.delete_iam is not None
    assert not ns.object_store.delete_iam.permits(cfg.CatalogIdentityRole.READER)
    assert not ns.object_store.delete_iam.permits(cfg.CatalogIdentityRole.WRITER)


def test_parquet_rejects_ipfs_as_data_path() -> None:
    with pytest.raises(cfg.PathPolicyError):
        cfg.normalize_parquet_data_path(
            "ipfs://bafybeiabc/data",
            storage_kind=cfg.ParquetStorageKind.VERSIONED_OBJECT,
        )


# ---------------------------------------------------------------------------
# Secrets and projections
# ---------------------------------------------------------------------------


def test_secret_profile_is_external_references_only() -> None:
    secrets = _secrets()
    projection = cfg.project_secret_profile(secrets)
    assert projection["quack_capability_ref"]["ref_id"].startswith("vault:")
    assert "token" not in projection
    assert "password" not in projection
    cfg.assert_no_secrets_in_projection(projection)


def test_embedded_token_rejected_as_secret_reference() -> None:
    with pytest.raises(cfg.SecretProfileError):
        cfg.ExternalSecretReference(
            ref_id="A" * 300,  # long base64-like blob
            purpose="token",
        )


def test_projection_rejects_embedded_password() -> None:
    with pytest.raises(cfg.SecretProfileError, match="secret material"):
        cfg.assert_no_secrets_in_projection({"password": "s3cr3t"})


def test_catalog_profile_projection_has_no_secrets() -> None:
    profile = _profile()
    projected = cfg.project_catalog_profile(profile)
    cfg.assert_no_secrets_in_projection(projected)
    assert projected["ducklake_supplies_authorization"] is False
    assert projected["remote_clients_may_open_catalog_file"] is False
    assert projected["single_owner_process"] is True
    assert projected["attach_safe_options"] == dict(ATTACH_SAFE_OPTIONS)


# ---------------------------------------------------------------------------
# Identities / least privilege / object delete
# ---------------------------------------------------------------------------


def test_default_identities_are_least_privilege() -> None:
    profile = _profile()
    reader = profile.identity(cfg.CatalogIdentityRole.READER)
    writer = profile.identity(cfg.CatalogIdentityRole.WRITER)
    maintainer = profile.identity(cfg.CatalogIdentityRole.MAINTAINER)
    broker = profile.identity(cfg.CatalogIdentityRole.OWNER_BROKER)

    assert reader.object_write is False
    assert reader.object_delete is False
    assert reader.open_catalog_file is False
    assert reader.inject_quack_capability is False

    assert writer.object_write is True
    assert writer.object_delete is False
    assert writer.open_catalog_file is False

    assert maintainer.open_catalog_file is False
    assert maintainer.inject_quack_capability is False
    assert maintainer.object_delete is False  # separate short-lived IAM

    assert broker.broker_authorize is True
    assert broker.inject_quack_capability is True
    assert broker.open_catalog_file is False


def test_reader_cannot_be_given_object_delete() -> None:
    with pytest.raises(cfg.CatalogProfileError):
        cfg.IdentityCapabilityProfile(
            role=cfg.CatalogIdentityRole.READER,
            os_identity="ducklake_reader",
            endpoint_access=True,
            object_read=True,
            object_write=False,
            object_delete=True,
        )


def test_object_delete_iam_unavailable_to_readers_writers() -> None:
    with pytest.raises(cfg.CatalogProfileError, match="unavailable to ordinary"):
        cfg.ObjectDeleteIamCapability(
            capability_ref=cfg.ExternalSecretReference(
                ref_id="vault:del",
                purpose="object_delete",
            ),
            allowed_roles=frozenset(
                {cfg.CatalogIdentityRole.READER, cfg.CatalogIdentityRole.MAINTAINER}
            ),
        )


# ---------------------------------------------------------------------------
# Catalog shard profile binding
# ---------------------------------------------------------------------------


def test_profile_binds_one_metadata_file_endpoint_lease_and_namespace() -> None:
    profile = _profile()
    assert profile.catalog_metadata.path.endswith("catalog_a.duckdb")
    assert profile.companion_registry.role == "companion_registry"
    assert profile.quack_endpoint.port == 19001
    assert profile.owner_lease.owner_generation == 1
    assert profile.owner_lease.fencing_epoch == 1
    assert profile.parquet_namespace.namespace_id == "catalog_a_ns"
    assert profile.same_shard_serialization is True
    assert profile.independent_shard_concurrency is True


def test_profile_rejects_ducklake_authorization_layer() -> None:
    with pytest.raises(cfg.CatalogProfileError, match="no role or authorization"):
        _profile(ducklake_supplies_authorization=True)


def test_profile_rejects_remote_open_of_catalog_file() -> None:
    with pytest.raises(cfg.CatalogProfileError, match="remote clients cannot"):
        _profile(remote_clients_may_open_catalog_file=True)


def test_catalog_and_registry_paths_must_differ() -> None:
    with pytest.raises(cfg.CatalogProfileError, match="distinct"):
        _profile(
            catalog_path="/var/lib/ducklake/catalogs/same.duckdb",
            registry_path="/var/lib/ducklake/catalogs/same.duckdb",
        )


# ---------------------------------------------------------------------------
# ATTACH options
# ---------------------------------------------------------------------------


def test_safe_attach_options_are_all_false() -> None:
    options = cfg.build_attach_options(cfg.AttachMode.SAFE)
    assert options.create_if_not_exists is False
    assert options.override_data_path is False
    assert options.automatic_migration is False
    assert options.ducklake_options() == {
        "CREATE_IF_NOT_EXISTS": False,
        "OVERRIDE_DATA_PATH": False,
        "AUTOMATIC_MIGRATION": False,
    }
    assert dict(ATTACH_SAFE_OPTIONS) == dict(options.ducklake_options())


def test_safe_attach_rejects_privileged_flags() -> None:
    with pytest.raises(cfg.CatalogProfileError, match="SAFE"):
        cfg.build_attach_options(
            cfg.AttachMode.SAFE,
            create_if_not_exists=True,
        )
    with pytest.raises(cfg.CatalogProfileError, match="SAFE"):
        cfg.build_attach_options(
            cfg.AttachMode.SAFE,
            override_data_path=True,
        )
    with pytest.raises(cfg.CatalogProfileError, match="SAFE"):
        cfg.build_attach_options(
            cfg.AttachMode.SAFE,
            automatic_migration=True,
        )


def test_bootstrap_and_migration_require_authorization_receipt() -> None:
    with pytest.raises(cfg.CatalogProfileError, match="authorization receipt"):
        cfg.build_attach_options(cfg.AttachMode.BOOTSTRAP, create_if_not_exists=True)
    options = cfg.build_attach_options(
        cfg.AttachMode.BOOTSTRAP,
        create_if_not_exists=True,
        authorization_receipt_id="boot-receipt-1",
    )
    assert options.create_if_not_exists is True
    assert options.mode is cfg.AttachMode.BOOTSTRAP

    migration = cfg.build_attach_options(
        cfg.AttachMode.MIGRATION,
        automatic_migration=True,
        authorization_receipt_id="migrate-receipt-1",
    )
    assert migration.automatic_migration is True


def test_attach_statement_sql_contains_safe_flags() -> None:
    profile = _profile()
    statement = cat.build_ducklake_attach_statement(profile, mode=cfg.AttachMode.SAFE)
    sql = statement.sql()
    assert "CREATE_IF_NOT_EXISTS false" in sql
    assert "OVERRIDE_DATA_PATH false" in sql
    assert "AUTOMATIC_MIGRATION false" in sql
    assert profile.catalog_metadata.path in sql
    assert profile.parquet_namespace.data_path in sql
    cat.require_safe_attach_options(statement.options)


def test_require_safe_attach_options_fails_on_true_flags() -> None:
    with pytest.raises(cat.CatalogError, match="CREATE_IF_NOT_EXISTS"):
        cat.require_safe_attach_options(
            {
                "CREATE_IF_NOT_EXISTS": True,
                "OVERRIDE_DATA_PATH": False,
                "AUTOMATIC_MIGRATION": False,
            }
        )


def test_profile_safe_attach_options_helper() -> None:
    profile = _profile()
    options = profile.safe_attach_options()
    assert options.mode is cfg.AttachMode.SAFE
    assert options.create_if_not_exists is False


# ---------------------------------------------------------------------------
# Remote access denial
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action",
    ["open", "mount", "copy", "mutate", "network_mount", "nfs_mount", "attach_path"],
)
def test_remote_clients_cannot_touch_catalog_file(action: str) -> None:
    with pytest.raises(cat.CatalogAccessDenied):
        cat.assert_remote_catalog_access_denied(action)


def test_remote_access_policy_forbids_all_file_actions() -> None:
    policy = cat.RemoteCatalogAccessPolicy()
    assert policy.may_open_catalog_file is False
    with pytest.raises(cat.CatalogAccessDenied):
        cat.RemoteCatalogAccessPolicy(may_open_catalog_file=True)


# ---------------------------------------------------------------------------
# Owner process: single owner, serialization, multi-shard
# ---------------------------------------------------------------------------


def test_single_owner_process_per_shard() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    result = runtime.owner.acquire_ownership(bootstrap=True)
    assert result["single_owner"] is True
    assert runtime.owner.state is cat.CatalogOwnerState.ACTIVE
    with pytest.raises(cat.CatalogError, match="already has an active owner"):
        runtime.owner.acquire_ownership(bootstrap=True)


def test_same_shard_requests_are_serialized() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    runtime.owner.acquire_ownership(bootstrap=True)
    events: list[str] = []
    release = threading.Event()
    first_started = threading.Event()
    errors: list[BaseException] = []

    def worker_one() -> None:
        try:
            def handler() -> str:
                events.append("1-start")
                first_started.set()
                assert release.wait(timeout=2)
                events.append("1-end")
                return "one"

            runtime.owner.submit_typed_request(
                kind=cat.CatalogRequestKind.WRITE,
                operation_id="op-1",
                handler=handler,
            )
        except BaseException as exc:  # pragma: no cover - test helper
            errors.append(exc)

    def worker_two() -> None:
        try:
            assert first_started.wait(timeout=2)

            def handler() -> str:
                events.append("2-start")
                events.append("2-end")
                return "two"

            runtime.owner.submit_typed_request(
                kind=cat.CatalogRequestKind.WRITE,
                operation_id="op-2",
                handler=handler,
            )
        except BaseException as exc:  # pragma: no cover - test helper
            errors.append(exc)

    t1 = threading.Thread(target=worker_one)
    t2 = threading.Thread(target=worker_two)
    t1.start()
    t2.start()
    assert first_started.wait(timeout=2)
    # Give worker_two time to block on the owner lock while worker_one holds it.
    time.sleep(0.05)
    assert "2-start" not in events
    release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not errors
    # Owner RLock serializes same-shard handlers: two cannot start until one ends.
    assert events == ["1-start", "1-end", "2-start", "2-end"]


def test_independent_shards_may_run_concurrently() -> None:
    registry = cat.CatalogShardRegistry()
    a = registry.register(_profile("catalog_a", port=19001))
    b = registry.register(_profile("catalog_b", port=19002))
    a.owner.acquire_ownership(bootstrap=True)
    b.owner.acquire_ownership(bootstrap=True)

    started = threading.Event()
    release = threading.Event()
    concurrent = threading.Event()
    errors: list[BaseException] = []

    def hold_a() -> None:
        try:
            def handler() -> str:
                started.set()
                if not release.wait(timeout=2):
                    raise TimeoutError("release not signaled")
                return "a"

            a.owner.submit_typed_request(
                kind=cat.CatalogRequestKind.WRITE,
                operation_id="op-a",
                handler=handler,
            )
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    def run_b() -> None:
        try:
            if not started.wait(timeout=2):
                raise TimeoutError("shard a did not start")
            # Shard B must not wait for shard A's lock.
            def handler() -> str:
                concurrent.set()
                return "b"

            b.owner.submit_typed_request(
                kind=cat.CatalogRequestKind.WRITE,
                operation_id="op-b",
                handler=handler,
            )
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    t_a = threading.Thread(target=hold_a)
    t_b = threading.Thread(target=run_b)
    t_a.start()
    t_b.start()
    t_b.join(timeout=3)
    release.set()
    t_a.join(timeout=3)
    assert not errors
    assert concurrent.is_set()
    assert len(registry) == 2


def test_registry_rejects_duplicate_metadata_path() -> None:
    registry = cat.CatalogShardRegistry()
    registry.register(_profile("catalog_a"))
    with pytest.raises(cat.CatalogError, match="already bound"):
        registry.register(
            _profile(
                "catalog_b",
                port=19002,
                catalog_path="/var/lib/ducklake/catalogs/catalog_a.duckdb",
                registry_path="/var/lib/ducklake/registries/catalog_b_registry.duckdb",
            )
        )


# ---------------------------------------------------------------------------
# Takeover
# ---------------------------------------------------------------------------


def test_takeover_requires_full_predecessor_fence_and_lock() -> None:
    decision = cat.evaluate_takeover_preconditions(_takeover(), profile=_profile())
    assert decision["allowed"] is True
    assert decision["native_file_lock"] == "acquired"


@pytest.mark.parametrize(
    "field,value",
    [
        ("admission_stopped", False),
        ("process_dead_or_fenced", False),
        ("endpoint_token_revoked", False),
        ("storage_capabilities_expired", False),
        ("all_handles_closed", False),
    ],
)
def test_takeover_fails_when_predecessor_evidence_incomplete(
    field: str, value: bool
) -> None:
    pred = _predecessor(**{field: value})
    with pytest.raises(cat.CatalogTakeoverError):
        cat.evaluate_takeover_preconditions(
            _takeover(predecessor=pred),
            profile=_profile(),
        )


def test_takeover_fails_without_native_file_lock() -> None:
    with pytest.raises(cat.CatalogTakeoverError, match="file-lock"):
        cat.evaluate_takeover_preconditions(
            _takeover(lock=cat.NativeFileLockStatus.HELD_BY_OTHER),
            profile=_profile(),
        )


def test_takeover_fails_on_catalog_digest_mismatch() -> None:
    with pytest.raises(cat.CatalogTakeoverError, match="digest"):
        cat.evaluate_takeover_preconditions(
            _takeover(expected_catalog_digest=_DIGEST_B),
            profile=_profile(),
        )


def test_owner_acquire_via_takeover() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    result = runtime.owner.acquire_ownership(preconditions=_takeover())
    assert result["owner_generation"] == 2
    assert runtime.owner.state is cat.CatalogOwnerState.ACTIVE


def test_owner_stop_admission_then_fence() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    runtime.owner.acquire_ownership(bootstrap=True)
    runtime.owner.stop_admission()
    assert runtime.owner.admits_requests is False
    with pytest.raises(cat.CatalogError, match="not admitting"):
        runtime.owner.submit_typed_request(
            kind=cat.CatalogRequestKind.READ,
            operation_id="op-x",
        )
    stopped = runtime.owner.fence_and_stop()
    assert stopped["admission_stopped"] is True
    assert stopped["handles_closed"] is True
    assert runtime.owner.state is cat.CatalogOwnerState.STOPPED


# ---------------------------------------------------------------------------
# Trusted broker + one-use Quack capability
# ---------------------------------------------------------------------------


def test_ducklake_has_no_authorization_layer_broker_authorizes() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    worker = _worker(role=cfg.CatalogIdentityRole.WRITER)
    decision = runtime.broker.authorize(
        worker=worker,
        request_kind=cat.CatalogRequestKind.WRITE,
        operation_id="op-1",
    )
    assert decision["authorized"] is True
    assert decision["ducklake_authorization_layer"] is False
    assert decision["authorized_by"] == "trusted_broker"


def test_untrusted_agent_never_receives_capability() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    agent = _worker(worker_id="agent-1", trusted=False)
    with pytest.raises(cat.CatalogAccessDenied, match="untrusted"):
        runtime.broker.authorize(
            worker=agent,
            request_kind=cat.CatalogRequestKind.READ,
            operation_id="op-agent",
        )
    with pytest.raises(cat.CatalogAccessDenied, match="untrusted"):
        runtime.broker.inject_one_use_quack_capability(worker=agent)


def test_one_use_quack_capability_injection_and_consume() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    worker = _worker(worker_id="trusted-worker", role=cfg.CatalogIdentityRole.WRITER)
    capability = runtime.broker.inject_one_use_quack_capability(
        worker=worker, ttl_seconds=30, now=1_000.0
    )
    projection = capability.as_mapping()
    assert projection["token"] == "***"
    assert "token" not in repr(capability) or "***" in repr(capability)
    cfg.assert_no_secrets_in_projection(projection)

    token = capability.reveal_token_for_trusted_worker()
    assert token
    assert token != "***"

    consumed = runtime.broker.consume_capability(
        capability, worker=worker, now=1_010.0
    )
    assert consumed["consumed"] is True
    with pytest.raises(cat.CatalogAccessDenied, match="already been consumed"):
        runtime.broker.consume_capability(capability, worker=worker, now=1_011.0)


def test_one_use_capability_expires() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    worker = _worker()
    capability = runtime.broker.inject_one_use_quack_capability(
        worker=worker, ttl_seconds=10, now=100.0
    )
    with pytest.raises(cat.CatalogAccessDenied, match="expired"):
        runtime.broker.consume_capability(capability, worker=worker, now=200.0)


def test_reader_cannot_maintain() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    reader = _worker(role=cfg.CatalogIdentityRole.READER)
    with pytest.raises(cat.CatalogAccessDenied):
        runtime.broker.authorize(
            worker=reader,
            request_kind=cat.CatalogRequestKind.MAINTAIN,
            operation_id="maint-1",
        )


def test_bootstrap_requires_owner_broker() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    writer = _worker(role=cfg.CatalogIdentityRole.WRITER)
    with pytest.raises(cat.CatalogAccessDenied, match="owner-broker"):
        runtime.broker.authorize(
            worker=writer,
            request_kind=cat.CatalogRequestKind.BOOTSTRAP,
            operation_id="boot-1",
        )
    broker_worker = _worker(
        worker_id="broker-1",
        role=cfg.CatalogIdentityRole.OWNER_BROKER,
    )
    decision = runtime.broker.authorize(
        worker=broker_worker,
        request_kind=cat.CatalogRequestKind.BOOTSTRAP,
        operation_id="boot-1",
    )
    assert decision["authorized"] is True


# ---------------------------------------------------------------------------
# Encryption defaults before first ingest
# ---------------------------------------------------------------------------


def test_encryption_defaults_present_before_ingest() -> None:
    profile = _profile()
    enc = profile.encryption.as_mapping()
    assert enc["catalog_at_rest"] is True
    assert enc["object_at_rest"] is True
    assert enc["transit_tls_required"] is True
    assert enc["key_ref"]["ref_id"].startswith("kms:")
    # Key material itself is never present.
    assert "raw_key" not in enc


# ---------------------------------------------------------------------------
# Runtime mapping is secret-free
# ---------------------------------------------------------------------------


def test_runtime_and_registry_projections_are_secret_free() -> None:
    registry = cat.CatalogShardRegistry()
    registry.register(_profile("catalog_a", port=19001))
    registry.register(_profile("catalog_b", port=19002))
    payload = dict(registry.as_mapping())
    cfg.assert_no_secrets_in_projection(payload)
    assert payload["independent_shard_concurrency"] is True
    assert payload["same_shard_serialization"] is True
    assert payload["shard_count"] == 2


def test_owner_safe_attach_statement_uses_profile_paths() -> None:
    runtime = cat.CatalogShardRuntime(profile=_profile())
    runtime.owner.acquire_ownership(bootstrap=True)
    statement = runtime.owner.safe_attach_statement(snapshot_version=7)
    opts = statement.ducklake_options()
    assert opts["CREATE_IF_NOT_EXISTS"] is False
    assert opts["OVERRIDE_DATA_PATH"] is False
    assert opts["AUTOMATIC_MIGRATION"] is False
    assert opts["SNAPSHOT_VERSION"] == 7
    assert "CREATE_IF_NOT_EXISTS false" in statement.sql()
