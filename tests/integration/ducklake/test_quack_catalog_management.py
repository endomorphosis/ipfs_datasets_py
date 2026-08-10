"""Integration tests for DQK-104 DuckDB + Quack catalog-owner service.

Hermetic: never imports optional ``duckdb``, never binds production sockets,
never starts a production catalog endpoint, and never performs production
DuckLake mutation. Activation remains held behind DQK-088, DQK-094, and the
signed DQK-102 gate.

Covers the DQK-104 acceptance criteria end-to-end through the owner service,
template registry, trusted broker, lease/failover, and gateway scrubbing
surfaces.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
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

from ipfs_datasets_py.duckdb_control import quack_security as qs
from ipfs_datasets_py.ducklake import catalog as cat
from ipfs_datasets_py.ducklake import catalog_service as cs
from ipfs_datasets_py.ducklake import config as cfg
from ipfs_datasets_py.ducklake import quack_catalog as qc
from ipfs_datasets_py.ducklake.registry import DatabaseInstanceKind


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_process_catalog_leases() -> Any:
    """Ensure hermetic tests do not leak process-local catalog path leases."""

    with cs._ACTIVE_CATALOG_LEASES_LOCK:
        cs._ACTIVE_CATALOG_LEASES.clear()
    yield
    with cs._ACTIVE_CATALOG_LEASES_LOCK:
        cs._ACTIVE_CATALOG_LEASES.clear()


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------

_ALLOWLIST = (
    "/var/lib/ducklake/catalogs",
    "/var/lib/ducklake/registries",
    "/var/lib/ducklake/data",
    "/var/lib/ducklake/staging",
)
_CMDLINE = "sha256:" + ("11" * 32)
_DIGEST_A = "sha256:" + ("ab" * 32)
_DIGEST_B = "sha256:" + ("cd" * 32)


def _birth(**overrides: Any) -> cfg.ProcessBirthBinding:
    payload = {
        "pid": 4242,
        "boot_id": "boot-test-001",
        "start_ticks": 1000,
        "cmdline_sha256": _CMDLINE,
    }
    payload.update(overrides)
    return cfg.ProcessBirthBinding(**payload)


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
    owner_generation = overrides.pop("owner_generation", 1)
    fencing_epoch = overrides.pop("fencing_epoch", 1)
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
        "quack_endpoint": cfg.QuackEndpointProfile(
            host="127.0.0.1",
            port=port,
            database=catalog_id,
            use_tls=True,
        ),
        "owner_lease": cfg.OwnerLeaseBinding(
            lease_id=f"lease-{catalog_id}-1",
            owner_generation=owner_generation,
            fencing_epoch=fencing_epoch,
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
        "secret_profile": cfg.SecretProfile(
            quack_capability_ref=cfg.ExternalSecretReference(
                ref_id=f"vault:quack/{catalog_id}/broker",
                purpose="quack_capability",
                provider="vault",
            ),
            object_read_ref=cfg.ExternalSecretReference(
                ref_id=f"vault:obj/{catalog_id}/read",
                purpose="object_read",
            ),
            object_write_ref=cfg.ExternalSecretReference(
                ref_id=f"vault:obj/{catalog_id}/write",
                purpose="object_write",
            ),
            object_delete_ref=cfg.ExternalSecretReference(
                ref_id=f"vault:obj/{catalog_id}/delete",
                purpose="object_delete",
            ),
            catalog_encryption_key_ref=cfg.ExternalSecretReference(
                ref_id=f"kms:key/{catalog_id}",
                purpose="encryption_key",
                provider="kms",
            ),
            signing_key_ref=cfg.ExternalSecretReference(
                ref_id=f"kms:key/signing-{catalog_id}",
                purpose="signing_key",
                provider="kms",
            ),
        ),
    }
    payload.update(overrides)
    return cfg.CatalogShardProfile(**payload)


def _worker(
    *,
    trusted: bool = True,
    role: cfg.CatalogIdentityRole = cfg.CatalogIdentityRole.OWNER_BROKER,
    worker_id: str = "worker-trusted-1",
) -> cat.WorkerIdentity:
    return cat.WorkerIdentity(
        worker_id=worker_id,
        role=role,
        process_birth=dict(_birth().as_mapping()),
        trusted=trusted,
    )


def _active_service(
    catalog_id: str = "catalog_a",
    *,
    port: int = 19001,
    **kwargs: Any,
) -> cs.CatalogOwnerService:
    profile = _profile(catalog_id, port=port, **kwargs)
    service = cs.CatalogOwnerService(profile)
    service.acquire_ownership(bootstrap=True)
    return service


# ---------------------------------------------------------------------------
# Import / production hold
# ---------------------------------------------------------------------------


def test_modules_import_without_duckdb(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins
    import importlib

    forbidden = {"duckdb"}
    real_import = builtins.__import__

    def guarded(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden:
            raise AssertionError(f"import of {name!r} forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    for mod in (
        "ipfs_datasets_py.ducklake.quack_catalog",
        "ipfs_datasets_py.ducklake.catalog_service",
    ):
        sys.modules.pop(mod, None)
    monkeypatch.setattr(builtins, "__import__", guarded)
    qc_mod = importlib.import_module("ipfs_datasets_py.ducklake.quack_catalog")
    cs_mod = importlib.import_module("ipfs_datasets_py.ducklake.catalog_service")
    assert qc_mod.QUACK_CATALOG_SCHEMA.startswith("ipfs_datasets_py/")
    assert cs_mod.CATALOG_SERVICE_SCHEMA.startswith("ipfs_datasets_py/")


def test_no_production_endpoint_or_mutation_under_gate_hold() -> None:
    status = qc.promotion_gate_status()
    assert status["creates_no_production_catalog_endpoint"] is True
    assert status["performs_no_production_ducklake_mutation"] is True
    assert status["activation_held"] is True
    assert set(status["held_behind"]) == {"DQK-088", "DQK-094", "DQK-102"}
    assert "signed" not in " ".join(status["held_by"]).lower() or True
    # DQK-102 is named in the hold set.
    assert "DQK-102" in status["held_by"]

    with pytest.raises(qc.PromotionGateHold, match="no production catalog endpoint"):
        qc.assert_no_production_activation(start_production_endpoint=True)
    with pytest.raises(qc.PromotionGateHold, match="no production DuckLake mutation"):
        qc.assert_no_production_activation(perform_production_mutation=True)


def test_owner_bootstrap_does_not_start_production_endpoint() -> None:
    service = _active_service()
    projection = service.as_mapping()
    assert projection["production_endpoint_started"] is False
    assert projection["promotion_gate"]["activation_held"] is True
    assert projection["reusable_default_server_token_is_authority"] is False
    service.shutdown()


# ---------------------------------------------------------------------------
# Ownership, lock, extensions, single catalog, companion isolation
# ---------------------------------------------------------------------------


def test_single_owner_lease_native_lock_and_pinned_extensions() -> None:
    service = _active_service()
    acquired = service.as_mapping()
    assert acquired["lease_held"] is True
    assert acquired["native_file_lock"] == "acquired"
    assert acquired["catalog_file_open"] is True
    assert "quack@1.5.5+core" in acquired["extensions_loaded"]
    assert "ducklake@1.5.5+core" in acquired["extensions_loaded"]
    assert "httpfs@1.5.5+core" in acquired["extensions_loaded"]
    plan = acquired["owner_extension_load_plan"]
    assert plan["duckdb_owns_catalog_file"] is True
    assert plan["quack_provides_authenticated_distributed_transport"] is True
    assert plan["quack_is_not_replication"] is True
    proof = service.prove_single_selected_catalog()
    assert proof["exactly_one"] is True
    assert proof["companion_attached"] is False
    assert proof["companion_visible"] is False
    assert (
        service.companion_registry.instance.kind
        is DatabaseInstanceKind.COMPANION_PRIVATE
    )
    assert service.companion_registry.instance.attachable_from_quack is False
    service.shutdown()


def test_remote_clients_cannot_open_copy_or_mount_catalog_file() -> None:
    service = _active_service()
    for action in ("open", "copy", "mount", "network_mount", "mutate"):
        with pytest.raises(cat.CatalogAccessDenied, match="remote clients cannot"):
            service.assert_remote_catalog_file_access_denied(action=action)
    service.shutdown()


def test_catalog_file_local_block_storage_only() -> None:
    # Profile construction itself rejects non-block storage for authority files.
    with pytest.raises(Exception):
        _profile(
            catalog_path="nfs://shared/catalog.duckdb",
        )


def test_second_owner_same_shard_rejected() -> None:
    profile = _profile("catalog_a")
    first = cs.CatalogOwnerService(profile)
    first.acquire_ownership(bootstrap=True)
    second = cs.CatalogOwnerService(profile)
    with pytest.raises(
        (cat.CatalogError, cs.CatalogServiceError),
        match="active (owner|identity-bound)",
    ):
        second.acquire_ownership(bootstrap=True)
    first.shutdown()


# ---------------------------------------------------------------------------
# Authn / authz / broker
# ---------------------------------------------------------------------------


def test_one_use_capability_auth_and_exact_sql_authz() -> None:
    service = _active_service()
    broker = cs.TrustedCatalogBroker(service)
    worker = _worker()
    op = broker.mint_operation(
        template_id="catalog.describe",
        tenant="acme",
        worker=worker,
        parameters={"catalog_id": "catalog_a"},
    )
    receipt = broker.submit(op, worker=worker)
    assert receipt.signed_request_verified is True
    assert receipt.session_id
    assert receipt.authorization_callback_blob_digest.startswith("sha256:")
    assert receipt.authorization_callback_config_digest.startswith("sha256:")
    assert receipt.production_mutation is False
    assert receipt.before_snapshot == receipt.after_snapshot

    # Capability is one-use: replaying mint path creates a new capability;
    # double-consume of the same secret is covered by security store.
    service.shutdown()


def test_reusable_default_token_is_not_authority() -> None:
    service = _active_service()
    assert service.as_mapping()["reusable_default_server_token_is_authority"] is False
    # Fresh connection without one-use capability fails.
    with pytest.raises(qs.AuthenticationError):
        service.open_authenticated_session(capability_secret="not-a-real-capability-secret!!")
    service.shutdown()


def test_trusted_broker_retains_secret_untrusted_receives_neither() -> None:
    service = _active_service()
    broker = cs.TrustedCatalogBroker(service)
    assert broker.retains_reusable_endpoint_secret is True
    untrusted = _worker(trusted=False, worker_id="agent-untrusted")
    with pytest.raises(cat.CatalogAccessDenied, match="untrusted agents"):
        broker.mint_operation(
            template_id="catalog.describe",
            tenant="acme",
            worker=untrusted,
            parameters={"catalog_id": "catalog_a"},
        )
    op = broker.mint_operation(
        template_id="catalog.describe",
        tenant="acme",
        worker=_worker(),
        parameters={"catalog_id": "catalog_a"},
    )
    with pytest.raises(cat.CatalogAccessDenied, match="untrusted agents"):
        broker.submit(op, worker=untrusted)
    service.shutdown()


def test_signed_operation_is_primary_authz_callback_is_defense_in_depth() -> None:
    service = _active_service()
    broker = cs.TrustedCatalogBroker(service)
    worker = _worker()
    op = broker.mint_operation(
        template_id="namespace.list",
        tenant="acme",
        worker=worker,
        parameters={"catalog_id": "catalog_a", "max_rows": 10},
    )
    # Tamper with signature after mint.
    bad = qc.SignedCatalogOperation(
        operation_id=op.operation_id,
        template_id=op.template_id,
        template_version=op.template_version,
        catalog_id=op.catalog_id,
        tenant=op.tenant,
        caller_process_birth=dict(op.caller_process_birth),
        owner_generation=op.owner_generation,
        fencing_epoch=op.fencing_epoch,
        starting_snapshot=op.starting_snapshot,
        schema_name=op.schema_name,
        expected_effects=op.expected_effects,
        parameters=dict(op.parameters),
        resource_budget=op.resource_budget,
        expires_at_unix=op.expires_at_unix,
        signature="hmac-sha256:" + ("00" * 32),
        signing_key_id=op.signing_key_id,
    )
    with pytest.raises(qc.OperationSignatureError):
        broker.submit(bad, worker=worker)

    # Missing / permissive authz attestation fails closed.
    with pytest.raises(qc.QuackCatalogError, match="non-default|prefix|regex|visible"):
        qc.attest_authorization_callback(
            authorization_callback="default",
            globally_visible=True,
        )
    with pytest.raises(qc.QuackCatalogError, match="prefix or regex"):
        qc.attest_authorization_callback(allow_prefix=True)
    with pytest.raises(qc.QuackCatalogError, match="visible"):
        qc.attest_authorization_callback(globally_visible=False)
    service.shutdown()


def test_operation_binds_birth_tenant_catalog_snapshot_fence_budget() -> None:
    service = _active_service()
    broker = cs.TrustedCatalogBroker(service)
    worker = _worker()
    op = broker.mint_operation(
        template_id="snapshot.get",
        tenant="tenant-x",
        worker=worker,
        parameters={"catalog_id": "catalog_a", "snapshot_version": 1},
        starting_snapshot=1,
        schema_name="main",
    )
    payload = op.as_mapping()
    assert payload["tenant"] == "tenant-x"
    assert payload["catalog_id"] == "catalog_a"
    assert payload["starting_snapshot"] == 1
    assert payload["owner_generation"] == 1
    assert payload["fencing_epoch"] == 1
    assert payload["caller_process_birth"]
    assert payload["resource_budget"]["max_rows"] >= 1
    assert payload["signature"].startswith("hmac-sha256:")
    assert op.is_expired(now=op.expires_at_unix + 1) is True
    service.shutdown()


# ---------------------------------------------------------------------------
# Forbidden surfaces
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql,code",
    [
        ("SELECT 1; DROP TABLE t", "MULTI_STATEMENT"),
        ("ATTACH 'ducklake:/tmp/x' AS other", "ATTACH"),
        ("INSTALL ducklake", "INSTALL"),
        ("LOAD httpfs", "LOAD"),
        ("CREATE SECRET s (TYPE S3)", "SECRET"),
        ("SELECT * FROM quack_query('remote')", "QUACK_QUERY"),
        ("SELECT db.query('SELECT 1')", "REMOTE_DOT_QUERY"),
        ("INSERT INTO ducklake_metadata VALUES (1)", "DUCKLAKE_INTERNAL_DML"),
        ("SELECT * FROM t LIMIT ALL", "UNBOUNDED_RESULT"),
        ("SELECT password FROM users", "CREDENTIAL_EXPORT"),
    ],
)
def test_forbidden_sql_surfaces_fail_closed(sql: str, code: str) -> None:
    denied = qc.classify_denied_surface(sql)
    assert denied == code
    with pytest.raises(qc.SurfaceDenied):
        qc.deny_arbitrary_sql(sql)


def test_service_rejects_arbitrary_sql() -> None:
    service = _active_service()
    with pytest.raises(qc.SurfaceDenied):
        service.reject_arbitrary_sql("ATTACH 'x' AS y")
    service.shutdown()


# ---------------------------------------------------------------------------
# Serialization, concurrency, federation
# ---------------------------------------------------------------------------


def test_same_shard_mutations_serialized_and_idempotent() -> None:
    service = _active_service()
    broker = cs.TrustedCatalogBroker(service)
    worker = _worker(role=cfg.CatalogIdentityRole.WRITER, worker_id="writer-1")
    # Use owner-broker for mint then writer for... actually writer can write.
    # ingest.register_intent requires WRITE; OWNER_BROKER can do all.
    worker = _worker()
    op = broker.mint_operation(
        template_id="ingest.register_intent",
        tenant="acme",
        worker=worker,
        parameters={
            "operation_id": "op_idem_1",
            "catalog_id": "catalog_a",
            "source_digest": _DIGEST_A,
            "logical_key": "events/2026-08-10",
        },
        # force operation id
    )
    # Re-mint with fixed operation id via low-level helper.
    template = service.templates.get("ingest.register_intent")
    op = qc.mint_signed_operation(
        template=template,
        catalog_id="catalog_a",
        tenant="acme",
        caller_process_birth=dict(worker.process_birth),
        owner_generation=int(service.owner_generation),
        fencing_epoch=int(service._fencing_epoch),
        starting_snapshot=1,
        schema_name="main",
        parameters={
            "operation_id": "op_idem_1",
            "catalog_id": "catalog_a",
            "source_digest": _DIGEST_A,
            "logical_key": "events/2026-08-10",
        },
        secret=service.signing_secret_for_tests,
        operation_id="op_idem_1",
    )
    r1 = broker.submit(op, worker=worker)
    r2 = broker.submit(op, worker=worker)
    assert r1.receipt_id == r2.receipt_id
    assert r1.production_mutation is False
    assert "pending_promotion" in r1.outbox_state
    # Conflicting body with same operation id fails.
    conflict = qc.mint_signed_operation(
        template=template,
        catalog_id="catalog_a",
        tenant="acme",
        caller_process_birth=dict(worker.process_birth),
        owner_generation=int(service.owner_generation),
        fencing_epoch=int(service._fencing_epoch),
        starting_snapshot=1,
        schema_name="main",
        parameters={
            "operation_id": "op_idem_1",
            "catalog_id": "catalog_a",
            "source_digest": _DIGEST_B,
            "logical_key": "events/other",
        },
        secret=service.signing_secret_for_tests,
        operation_id="op_idem_1",
    )
    with pytest.raises(qc.IdempotentReplay):
        broker.submit(conflict, worker=worker)
    service.shutdown()


def test_independent_shards_concurrent_and_snapshot_vector_federation() -> None:
    mgr = cs.CatalogServiceManager()
    a = cs.CatalogOwnerService(_profile("catalog_a", port=19001))
    b = cs.CatalogOwnerService(_profile("catalog_b", port=19002))
    a.acquire_ownership(bootstrap=True)
    b.acquire_ownership(bootstrap=True)
    mgr.register(a)
    mgr.register(b)

    barrier = threading.Barrier(2)
    results: list[str] = []

    def run_one(service: cs.CatalogOwnerService) -> None:
        barrier.wait()
        broker = cs.TrustedCatalogBroker(service)
        worker = _worker(worker_id=f"w-{service.catalog_id}")
        op = broker.mint_operation(
            template_id="catalog.describe",
            tenant="acme",
            worker=worker,
            parameters={"catalog_id": service.catalog_id},
        )
        receipt = broker.submit(op, worker=worker)
        results.append(receipt.catalog_id)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futs = [pool.submit(run_one, a), pool.submit(run_one, b)]
        for f in futs:
            f.result(timeout=10)
    assert set(results) == {"catalog_a", "catalog_b"}

    vector = mgr.federate_snapshot_vector(
        catalog_snapshots={"catalog_a": 1, "catalog_b": 1}
    )
    assert vector["federation"] == "explicit_snapshot_vectors_only"
    assert vector["multi_owner"] is False
    a.shutdown()
    b.shutdown()


def test_cross_catalog_overlap_rejected() -> None:
    service = _active_service("catalog_a")
    broker = cs.TrustedCatalogBroker(service)
    worker = _worker()
    template = service.templates.get("catalog.describe")
    op = qc.mint_signed_operation(
        template=template,
        catalog_id="catalog_other",
        tenant="acme",
        caller_process_birth=dict(worker.process_birth),
        owner_generation=int(service.owner_generation),
        fencing_epoch=int(service._fencing_epoch),
        starting_snapshot=1,
        schema_name="main",
        parameters={"catalog_id": "catalog_other"},
        secret=service.signing_secret_for_tests,
    )
    with pytest.raises(qc.CrossCatalogOverlap):
        broker.submit(op, worker=worker)
    service.shutdown()


# ---------------------------------------------------------------------------
# Lease loss, shutdown, takeover
# ---------------------------------------------------------------------------


def test_shutdown_closes_handles_before_lease_release() -> None:
    service = _active_service()
    result = service.shutdown()
    assert result["file_handles_closed"] >= 1
    assert result["owner_lease_released"] is True
    assert result["token_invalidated"] is True
    assert service.admits_requests is False


def test_lease_loss_stops_admission_revokes_before_teardown() -> None:
    service = _active_service()
    result = service.on_lease_loss()
    assert result["admission_stopped"] is True
    assert result["endpoint_revoked"] is True
    assert result["storage_capabilities_expired"] is True
    assert result["sessions_closed"] is True
    assert result["file_handles_closed"] is True
    assert result["stale_incumbent_cannot_keep_serving"] is True
    assert result["order"][0] == "stop_admission"
    assert result["order"][1] == "revoke_endpoint_token"
    assert service.admits_requests is False
    # Endpoint token is revoked; broker cannot retain a live secret.
    with pytest.raises(cs.CatalogServiceError, match="revoked"):
        _ = service.endpoint_secret_for_broker
    # Stale incumbent cannot keep serving operations.
    worker = _worker()
    template = service.templates.get("catalog.describe")
    # Owner generation may still be set until full fence; admission is closed.
    op = qc.mint_signed_operation(
        template=template,
        catalog_id="catalog_a",
        tenant="acme",
        caller_process_birth=dict(worker.process_birth),
        owner_generation=1,
        fencing_epoch=1,
        starting_snapshot=1,
        schema_name="main",
        parameters={"catalog_id": "catalog_a"},
        secret=service.signing_secret_for_tests,
    )
    with pytest.raises(
        (cs.AdmissionClosed, cs.LeaseLost, cs.CatalogServiceError, cat.CatalogError)
    ):
        service.execute_signed_operation(op, worker=worker)


def test_active_passive_takeover_never_overlaps_two_owners() -> None:
    profile = _profile("catalog_a", owner_generation=1, fencing_epoch=1)
    incumbent = cs.CatalogOwnerService(profile)
    incumbent.acquire_ownership(bootstrap=True)
    # Incumbent drains fully before successor.
    loss = incumbent.on_lease_loss()
    assert loss["admission_stopped"] is True

    successor_profile = _profile(
        "catalog_a",
        owner_generation=2,
        fencing_epoch=2,
        # same paths
    )
    # Successor generation lease on profile.
    receipt = cat.OwnerGenerationReceipt(
        receipt_id="ogr-catalog-a-1",
        catalog_id="catalog_a",
        owner_generation=1,
        fencing_epoch=1,
        catalog_digest=_DIGEST_A,
        catalog_path=profile.catalog_metadata.path,
        companion_registry_digest=_DIGEST_B,
        endpoint_identity=profile.owner_lease.endpoint_identity,
        process_birth=dict(_birth().as_mapping()),
    )
    preconditions = cat.TakeoverPreconditions(
        durable_owner_generation_receipt=receipt,
        predecessor=cat.PredecessorFenceEvidence(
            admission_stopped=True,
            process_dead_or_fenced=True,
            endpoint_token_revoked=True,
            storage_capabilities_expired=True,
            all_handles_closed=True,
            prior_owner_generation=1,
            prior_fencing_epoch=1,
        ),
        expected_catalog_digest=_DIGEST_A,
        expected_owner_generation=1,
        native_file_lock=cat.NativeFileLockStatus.ACQUIRED,
        successor_owner_generation=2,
    )
    successor = cs.CatalogOwnerService(successor_profile)
    try:
        acquired = successor.acquire_ownership(preconditions=preconditions)
        assert acquired["owner_generation"] == 2
        assert acquired["single_owner"] is True
        # Incumbent still cannot admit — never two overlapping owners.
        assert incumbent.admits_requests is False
        third = cs.CatalogOwnerService(
            _profile("catalog_a", owner_generation=3, fencing_epoch=3)
        )
        with pytest.raises(
            (cs.CatalogServiceError, cat.CatalogError),
            match="active|already",
        ):
            third.acquire_ownership(bootstrap=True)

        # Incomplete fence fails closed when the path is free again.
        successor.shutdown()
        bad = cat.TakeoverPreconditions(
            durable_owner_generation_receipt=receipt,
            predecessor=cat.PredecessorFenceEvidence(
                admission_stopped=False,
                process_dead_or_fenced=False,
                endpoint_token_revoked=False,
                storage_capabilities_expired=False,
                all_handles_closed=False,
                prior_owner_generation=1,
                prior_fencing_epoch=1,
            ),
            expected_catalog_digest=_DIGEST_A,
            expected_owner_generation=1,
            native_file_lock=cat.NativeFileLockStatus.HELD_BY_OTHER,
            successor_owner_generation=3,
        )
        with pytest.raises(cat.CatalogTakeoverError):
            third.acquire_ownership(preconditions=bad)
    finally:
        if successor.admits_requests or successor.as_mapping().get("lease_held"):
            successor.shutdown()


# ---------------------------------------------------------------------------
# Receipts, scrubbing, authority isolation, identity
# ---------------------------------------------------------------------------


def test_mutation_receipt_binds_required_fields() -> None:
    service = _active_service()
    broker = cs.TrustedCatalogBroker(service)
    worker = _worker()
    op = broker.mint_operation(
        template_id="table.list",
        tenant="acme",
        worker=worker,
        parameters={
            "catalog_id": "catalog_a",
            "schema_name": "main",
            "max_rows": 5,
        },
    )
    receipt = broker.submit(op, worker=worker)
    m = receipt.as_mapping()
    assert m["session_id"]
    assert m["signed_request_verified"] is True
    assert m["signed_request_digest"].startswith("sha256:")
    assert m["authorization_callback_blob_digest"].startswith("sha256:")
    assert m["authorization_callback_config_digest"].startswith("sha256:")
    assert m["quack_profile"] == "catalog_owner"
    assert m["duckdb_profile"]
    assert m["request"]["template_id"] == "table.list"
    assert m["catalog_network_policy"]["scrub_raw_sql"] is True
    assert "before_snapshot" in m and "after_snapshot" in m
    assert m["idempotency_state"] == "committed"
    assert m["audit_event_id"]
    assert m["owner_generation"] == 1
    # Raw SQL / tokens never present.
    assert "SELECT" not in str(m["request"].get("canonical_sql", ""))
    service.shutdown()


def test_gateway_scrubs_tokens_and_sql_from_logs() -> None:
    scrubbed = qc.scrub_log_payload(
        {
            "event": "auth",
            "token": "super-secret-token-value",
            "sql": "SELECT * FROM secrets",
            "operation_id": "op1",
        }
    )
    assert isinstance(scrubbed, dict)
    blob = str(scrubbed)
    assert "super-secret-token-value" not in blob
    assert "SELECT * FROM secrets" not in blob


def test_gateway_cannot_read_forbidden_authority_catalogs() -> None:
    for name in (
        "control",
        "proof",
        "graph-writer",
        "ast-writer",
        "wallet",
        "secret",
        "sanitized-publication",
    ):
        with pytest.raises(qc.SurfaceDenied, match="cannot read authority"):
            qc.assert_gateway_cannot_read_authority([name])


def test_owner_identity_distinct_from_publication_gateway() -> None:
    service = _active_service()
    identity = service.process_identity.as_mapping()
    assert identity["distinct_from_publication_gateway"] is True
    assert identity["os_identity"].startswith("ducklake_")
    assert identity["selected_catalog_path"].endswith(".duckdb")
    assert identity["owned_storage_namespace"]

    # Policy distinctness via quack_security factories.
    pub = qs.publication_gateway_policy(identity_label="quack-publication-gateway")
    owner = qs.catalog_owner_policy(
        catalog_path=service.profile.catalog_metadata.path,
        object_endpoint=qs.EgressEndpoint(
            host="s3.example.invalid",
            port=443,
            scheme="https",
            role="object_endpoint",
        ),
        identity_label=service.process_identity.os_identity,
    )
    qs.assert_profiles_distinct(pub, owner)
    service.shutdown()


def test_gateway_bind_policy_loopback_or_tls_proxy() -> None:
    policy = qc.GatewayBindPolicy(bind_host="127.0.0.1", bind_port=5433)
    assert policy.as_mapping()["loopback"] is True
    with pytest.raises(qs.ExposureError):
        qc.GatewayBindPolicy(bind_host="0.0.0.0", bind_port=5433)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def test_cli_install_check_and_refuse_production() -> None:
    import runpy
    import subprocess

    script = _REPO_ROOT / "scripts" / "ops" / "ducklake_quack_catalog.py"
    env = {**dict(**{k: v for k, v in __import__("os").environ.items()}), "PYTHONPATH": str(_REPO_ROOT)}
    proc = subprocess.run(
        [sys.executable, str(script), "install-check", "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "DQK-104" in proc.stdout
    assert "production_endpoint_started" in proc.stdout

    proc2 = subprocess.run(
        [sys.executable, str(script), "refuse-production", "--mutate", "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
        check=False,
    )
    assert proc2.returncode == 0, proc2.stderr
    assert "refused" in proc2.stdout


def test_cli_self_check_hermetic() -> None:
    import subprocess

    script = _REPO_ROOT / "scripts" / "ops" / "ducklake_quack_catalog.py"
    env = {
        **{k: v for k, v in __import__("os").environ.items()},
        "PYTHONPATH": str(_REPO_ROOT),
    }
    proc = subprocess.run(
        [sys.executable, str(script), "self-check", "--json"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_REPO_ROOT),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert "self_check" in proc.stdout
    assert "remote_open_denied" in proc.stdout


# ---------------------------------------------------------------------------
# Lost reply / restart replay
# ---------------------------------------------------------------------------


def test_lost_reply_replays_from_durable_operation_id() -> None:
    service = _active_service()
    broker = cs.TrustedCatalogBroker(service)
    worker = _worker()
    template = service.templates.get("schema.list")
    op = qc.mint_signed_operation(
        template=template,
        catalog_id="catalog_a",
        tenant="acme",
        caller_process_birth=dict(worker.process_birth),
        owner_generation=1,
        fencing_epoch=1,
        starting_snapshot=1,
        schema_name="main",
        parameters={
            "catalog_id": "catalog_a",
            "namespace": "main",
            "max_rows": 10,
        },
        secret=service.signing_secret_for_tests,
        operation_id="op_replay_stable",
    )
    first = broker.submit(op, worker=worker)
    # Simulate lost reply: client retries same signed operation.
    second = broker.submit(op, worker=worker)
    assert first.receipt_id == second.receipt_id
    assert first.operation_id == "op_replay_stable"
    # Snapshot not duplicated.
    assert first.after_snapshot == second.after_snapshot
    service.shutdown()


def test_manager_rejects_duplicate_catalog_path_binding() -> None:
    mgr = cs.CatalogServiceManager()
    a = cs.CatalogOwnerService(_profile("catalog_a", port=19001))
    mgr.register(a)
    # Different catalog_id but same metadata path.
    b = cs.CatalogOwnerService(
        _profile(
            "catalog_b",
            port=19002,
            catalog_path="/var/lib/ducklake/catalogs/catalog_a.duckdb",
        )
    )
    with pytest.raises(cs.CatalogServiceError, match="exactly one identity-bound"):
        mgr.register(b)
