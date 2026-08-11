"""Hermetic tests for allowlisted DuckLake query/export APIs (DQK-093).

Acceptance coverage:

* Every operation is an allowlisted parameterized template
* Catalog-management calls use DQK-104 while query/export use snapshot-bound
  workers or the sanitized publication plane
* Pagination, cancellation, snapshot/time-travel selection, and export digests
  are bounded and reproducible
* Secrets, encryption keys, raw catalog strings, Quack tokens, and unrestricted
  object URIs are redacted
* Untrusted remote access remains a typed broker or sanitized publication
  operation rather than direct authority-catalog Quack access

Also covers CLI dispatch, MCP entrypoints, and import-time inertness.
"""

from __future__ import annotations

import builtins
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_REPO_ROOT = Path(__file__).resolve().parents[2]
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

from ipfs_datasets_py.duckdb_control.contracts import SnapshotId
from ipfs_datasets_py.duckdb_control import query_registry as qr
from ipfs_datasets_py.ducklake import api as lake_api
from ipfs_datasets_py.ducklake import cli as lake_cli
from ipfs_datasets_py.ducklake import catalog as cat
from ipfs_datasets_py.ducklake import catalog_service as cs
from ipfs_datasets_py.ducklake import config as cfg
from ipfs_datasets_py.mcp_server.tools import duckdb_query_tools as dqt


TENANT = "tenant:alpha"
FIXED_CLOCK = "2026-08-10T12:00:00Z"
SNAPSHOT = "snap-lake-001"
CATALOG_ID = "catalog_a"

_ALLOWLIST = (
    "/var/lib/ducklake/catalogs",
    "/var/lib/ducklake/registries",
    "/var/lib/ducklake/data",
    "/var/lib/ducklake/staging",
)
_CMDLINE = "sha256:" + ("11" * 32)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _snapshot(value: str = SNAPSHOT) -> SnapshotId:
    return SnapshotId(value=value, store_generation=1)


class FakeBackend:
    def __init__(self, rows: Sequence[Mapping[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.calls: list[tuple[str, Sequence[Any] | None]] = []

    def execute(
        self, sql: str, parameters: Sequence[Any] | None = None
    ) -> Sequence[Mapping[str, Any]]:
        self.calls.append((sql, parameters))
        return list(self.rows)


def _aggregate_rows(n: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "catalog_id": CATALOG_ID,
            "dataset_id": f"ds_{i:03d}",
            "tenant_id": TENANT,
            "row_count": 10 * (i + 1),
            "snapshot_version": 1,
        }
        for i in range(n)
    ]


def _api(
    *,
    rows: Sequence[Mapping[str, Any]] | None = None,
    include_builtins: bool = False,
) -> tuple[lake_api.DuckLakeQueryAPI, FakeBackend]:
    registry = qr.open_default_registry(include_builtins=include_builtins)
    for template in lake_api.default_ducklake_query_templates():
        if template.template_id in registry:
            registry.register(template, replace=True)
        else:
            registry.register(template)
    backend = FakeBackend(rows=rows if rows is not None else _aggregate_rows(5))
    executor = qr.QueryExecutor(
        registry,
        backend=backend,
        audit_log=qr.AuditLog(),
        clock=lambda: FIXED_CLOCK,
    )
    api = lake_api.DuckLakeQueryAPI(
        registry=registry,
        executor=executor,
        clock=lambda: FIXED_CLOCK,
        page_token_secret=b"test-secret-key-32-bytes-long!!",
        include_lake_templates=False,
        include_builtin_query_templates=False,
        catalog_projections=(
            lake_api.CatalogProjection(
                catalog_id=CATALOG_ID,
                owner_generation=1,
                fencing_epoch=1,
                snapshot_version=1,
                admits_requests=True,
            ),
        ),
        dataset_projections=(
            lake_api.DatasetProjection(
                catalog_id=CATALOG_ID,
                namespace="main",
                schema_name="main",
                dataset_id="orders",
                snapshot_version=1,
            ),
            lake_api.DatasetProjection(
                catalog_id=CATALOG_ID,
                namespace="main",
                schema_name="main",
                dataset_id="events",
                snapshot_version=1,
            ),
        ),
        retained_snapshots={CATALOG_ID: (1, 2, 3)},
    )
    return api, backend


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
    catalog_id: str = CATALOG_ID,
    *,
    port: int = 19101,
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


@pytest.fixture(autouse=True)
def _clear_process_catalog_leases() -> Any:
    with cs._ACTIVE_CATALOG_LEASES_LOCK:
        cs._ACTIVE_CATALOG_LEASES.clear()
    yield
    with cs._ACTIVE_CATALOG_LEASES_LOCK:
        cs._ACTIVE_CATALOG_LEASES.clear()


# ---------------------------------------------------------------------------
# Import-time safety
# ---------------------------------------------------------------------------


def test_api_and_tools_import_without_duckdb(monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = {"duckdb", "duckdb.experimental"}
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: ANN001
        root = name.split(".", 1)[0]
        if root in forbidden or name in forbidden:
            raise AssertionError(f"import of {name!r} is forbidden at module import")
        return real_import(name, globals, locals, fromlist, level)

    for mod in (
        "ipfs_datasets_py.ducklake.api",
        "ipfs_datasets_py.ducklake.cli",
        "ipfs_datasets_py.mcp_server.tools.duckdb_query_tools",
    ):
        sys.modules.pop(mod, None)
    monkeypatch.setattr(builtins, "__import__", guarded_import)
    api_mod = importlib.import_module("ipfs_datasets_py.ducklake.api")
    cli_mod = importlib.import_module("ipfs_datasets_py.ducklake.cli")
    tools_mod = importlib.import_module(
        "ipfs_datasets_py.mcp_server.tools.duckdb_query_tools"
    )
    assert api_mod.DUCKLAKE_API_SCHEMA.endswith("@1")
    assert cli_mod.CLI_SCHEMA.endswith("@1")
    assert tools_mod.DUCKLAKE_TOOLS_SCHEMA.endswith("@1")
    monkeypatch.setattr(builtins, "__import__", real_import)


# ---------------------------------------------------------------------------
# Template allowlist + SQL denial
# ---------------------------------------------------------------------------


def test_query_rejects_raw_sql_argument() -> None:
    api, _ = _api()
    with pytest.raises(lake_api.DuckLakeAPIError) as exc:
        api.query(
            "ducklake.aggregate_count",
            {
                "tenant_id": TENANT,
                "catalog_id": CATALOG_ID,
                "dataset_id": "orders",
                "row_limit": 2,
            },
            snapshot_id=_snapshot(),
            tenant_id=TENANT,
            sql="SELECT * FROM secrets",
        )
    assert exc.value.reason_code == "query.sql_surface_denied"
    public = lake_api.sanitize_public_error(exc.value)
    assert "SELECT" not in public["error"]
    assert "secrets" not in public["error"].lower()


def test_mcp_query_rejects_raw_sql_without_raising() -> None:
    api, _ = _api()
    result = dqt.ducklake_query(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
        },
        snapshot_id=SNAPSHOT,
        tenant_id=TENANT,
        sql="DROP TABLE users",
        api=api,
    )
    assert result["status"] == "error"
    assert result["reason_code"] == "query.sql_surface_denied"
    assert "DROP" not in result["error"]


def test_query_rejects_sql_smuggled_as_parameter_key() -> None:
    api, _ = _api()
    with pytest.raises(lake_api.DuckLakeAPIError) as exc:
        api.query(
            "ducklake.aggregate_count",
            {
                "tenant_id": TENANT,
                "catalog_id": CATALOG_ID,
                "dataset_id": "orders",
                "sql": "SELECT password FROM t",
            },
            snapshot_id=_snapshot(),
            tenant_id=TENANT,
        )
    assert exc.value.reason_code == "query.sql_surface_denied"


def test_unknown_template_is_denied() -> None:
    api, _ = _api()
    result = dqt.ducklake_query(
        "not.a.real.template",
        {"tenant_id": TENANT, "catalog_id": CATALOG_ID, "dataset_id": "orders"},
        snapshot_id=SNAPSHOT,
        tenant_id=TENANT,
        api=api,
    )
    assert result["status"] == "error"
    assert result["reason_code"] == "query.unknown_template"


def test_list_templates_are_allowlisted_parameterized() -> None:
    api, _ = _api(include_builtins=True)
    untrusted = api.list_templates(trust="untrusted")
    assert untrusted["status"] == "ok"
    ids = {t["template_id"] for t in untrusted["templates"]}
    assert "ducklake.aggregate_count" in ids
    assert "ducklake.discover_datasets" in ids
    for item in untrusted["templates"]:
        assert "sql" not in item
        assert "canonical_sql" not in item
        assert item["kind"] == "query"
    trusted = api.list_templates(trust="trusted", include_catalog_templates=True)
    kinds = {t["kind"] for t in trusted["templates"]}
    assert "catalog_management" in kinds
    catalog_ids = {
        t["template_id"]
        for t in trusted["templates"]
        if t["kind"] == "catalog_management"
    }
    assert "table.list" in catalog_ids
    assert "snapshot.get" in catalog_ids


# ---------------------------------------------------------------------------
# Discovery + snapshot selection
# ---------------------------------------------------------------------------


def test_discover_catalogs_redacts_credentials_and_paths() -> None:
    api, _ = _api()
    result = api.discover_catalogs(tenant_id=TENANT, trust="untrusted")
    assert result["status"] == "ok"
    assert result["operation"] == "discover_catalogs"
    assert result["direct_authority_quack_access"] is False
    assert result["plane"] == lake_api.AccessPlane.PUBLICATION_PLANE.value
    assert result["count"] >= 1
    for catalog in result["catalogs"]:
        assert catalog["catalog_id"] == CATALOG_ID
        assert catalog["catalog_path"] == "***REDACTED***"
        assert catalog["quack_token"] == "***REDACTED***"
        assert catalog["credentials"] == "***REDACTED***"
        assert catalog["object_uri"] == "***REDACTED***"
    blob = str(result)
    assert "/var/lib/ducklake" not in blob
    assert "vault:" not in blob


def test_discover_datasets_untrusted_uses_publication_plane() -> None:
    api, _ = _api()
    result = api.discover_datasets(
        catalog_id=CATALOG_ID,
        tenant_id=TENANT,
        trust="untrusted",
    )
    assert result["status"] == "ok"
    assert result["plane"] == lake_api.AccessPlane.PUBLICATION_PLANE.value
    assert result["template_id"] == "ducklake.discover_datasets"
    assert result["direct_authority_quack_access"] is False
    names = {d["dataset_id"] for d in result["datasets"]}
    assert names == {"orders", "events"}
    for dataset in result["datasets"]:
        assert dataset["catalog_path"] == "***REDACTED***"
        assert dataset["object_uri"] == "***REDACTED***"


def test_discover_datasets_trusted_uses_dqk104_catalog_template() -> None:
    api, _ = _api()
    profile = _profile(CATALOG_ID, port=19111)
    service = cs.CatalogOwnerService(profile)
    service.acquire_ownership(bootstrap=True)
    # Seed tables for the table.list affected objects path.
    service._tables["main"] = {"orders", "payments"}
    api.register_owner_service(service)
    worker = _worker(trusted=True)
    result = api.discover_datasets(
        catalog_id=CATALOG_ID,
        tenant_id=TENANT,
        trust="trusted",
        worker=worker,
    )
    assert result["status"] == "ok"
    assert result["plane"] == lake_api.AccessPlane.CATALOG_MANAGEMENT.value
    assert result["template_id"] == "table.list"
    assert result["direct_authority_quack_access"] is False
    assert "catalog_receipt" in result
    assert result["catalog_receipt"]["template_identity"].startswith("table.list@")
    assert "canonical_sql" not in result["catalog_receipt"]
    assert "token" not in str(result).lower() or "***REDACTED***" in str(result)
    names = {d["dataset_id"] for d in result["datasets"]}
    assert "orders" in names
    assert "payments" in names
    service.shutdown()


def test_untrusted_worker_cannot_use_catalog_management_path() -> None:
    api, _ = _api()
    profile = _profile(CATALOG_ID, port=19112)
    service = cs.CatalogOwnerService(profile)
    service.acquire_ownership(bootstrap=True)
    api.register_owner_service(service)
    worker = _worker(trusted=False, role=cfg.CatalogIdentityRole.READER)
    with pytest.raises(lake_api.DuckLakeAPIError) as exc:
        api.discover_datasets(
            catalog_id=CATALOG_ID,
            tenant_id=TENANT,
            trust="trusted",
            worker=worker,
        )
    assert exc.value.reason_code == "ducklake_api.untrusted_catalog_access"
    service.shutdown()


def test_select_snapshot_bounded_and_reproducible() -> None:
    api, _ = _api()
    first = api.select_snapshot(
        catalog_id=CATALOG_ID,
        snapshot_version=2,
        tenant_id=TENANT,
        trust="untrusted",
        time_travel=True,
        logical_query_id="q-replay-1",
    )
    second = api.select_snapshot(
        catalog_id=CATALOG_ID,
        snapshot_version=2,
        tenant_id=TENANT,
        trust="untrusted",
        time_travel=True,
        logical_query_id="q-replay-1",
    )
    assert first["status"] == "ok"
    assert first["operation"] == "select_snapshot"
    assert first["bounded"] is True
    assert first["reproducible"] is True
    assert first["selection"]["snapshot_version"] == 2
    assert first["selection"]["retained"] is True
    assert (
        first["selection"]["logical_result_digest"]
        == second["selection"]["logical_result_digest"]
    )
    assert first["selection"]["logical_result_digest"].startswith("sha256:")


def test_select_snapshot_time_travel_outside_retention_fails() -> None:
    api, _ = _api()
    with pytest.raises(lake_api.DuckLakeAPIError) as exc:
        api.select_snapshot(
            catalog_id=CATALOG_ID,
            snapshot_version=99,
            tenant_id=TENANT,
            time_travel=True,
        )
    assert exc.value.reason_code == "ducklake_api.snapshot_not_retained"


def test_select_snapshot_trusted_uses_dqk104() -> None:
    api, _ = _api()
    profile = _profile(CATALOG_ID, port=19113)
    service = cs.CatalogOwnerService(profile)
    service.acquire_ownership(bootstrap=True)
    api.register_owner_service(service)
    worker = _worker(trusted=True)
    result = api.select_snapshot(
        catalog_id=CATALOG_ID,
        snapshot_version=1,
        tenant_id=TENANT,
        trust="trusted",
        worker=worker,
    )
    assert result["status"] == "ok"
    assert result["plane"] == lake_api.AccessPlane.CATALOG_MANAGEMENT.value
    assert result["template_id"] == "snapshot.get"
    assert "catalog_receipt" in result
    service.shutdown()


# ---------------------------------------------------------------------------
# Query / explain / plane selection
# ---------------------------------------------------------------------------


def test_query_uses_publication_plane_for_untrusted() -> None:
    api, backend = _api(rows=_aggregate_rows(3))
    result = api.query(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
            "row_limit": 3,
        },
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        trust="untrusted",
        page_size=10,
        catalog_id=CATALOG_ID,
    )
    assert result["status"] == "ok"
    assert result["operation"] == "query"
    assert result["plane"] == lake_api.AccessPlane.PUBLICATION_PLANE.value
    assert result["direct_authority_quack_access"] is False
    assert result["bounded"] is True
    assert result["row_count"] == 3
    assert result["snapshot"]["value"] == SNAPSHOT
    assert result["receipt"]["parameters_digest"].startswith("sha256:")
    assert len(backend.calls) == 1
    assert "lake_aggregate_counts" in backend.calls[0][0]


def test_query_uses_snapshot_bound_worker_plane_for_trusted() -> None:
    api, _ = _api(rows=_aggregate_rows(2))
    result = api.query(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
        },
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        trust="trusted",
    )
    assert result["status"] == "ok"
    assert result["plane"] == lake_api.AccessPlane.SNAPSHOT_BOUND_WORKER.value
    assert result["direct_authority_quack_access"] is False


def test_explain_omits_raw_sql_and_bind_values() -> None:
    api, _ = _api()
    result = api.explain(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
            "row_limit": 5,
        },
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
    )
    assert result["status"] == "ok"
    assert result["operation"] == "explain"
    assert "sql" not in result or result.get("sql") in (None, "")
    assert "bind_values" not in result
    redacted = result["sql_redacted"]
    assert redacted
    assert "SELECT" not in redacted or "***REDACTED***" in redacted
    assert "lake_aggregate_counts" not in redacted


# ---------------------------------------------------------------------------
# Pagination + cancellation
# ---------------------------------------------------------------------------


def test_bounded_pagination_and_page_token() -> None:
    rows = _aggregate_rows(7)
    api, _ = _api(rows=rows)
    first = api.query(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
            "row_limit": 100,
        },
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        page_size=3,
    )
    assert first["status"] == "ok"
    assert first["row_count"] == 3
    assert first["total_row_count"] == 7
    assert first["has_more"] is True
    assert first["next_page_token"]
    handle_id = first["handle_id"]

    second = api.page(handle_id, first["next_page_token"])
    assert second["status"] == "ok"
    assert second["operation"] == "page"
    assert second["offset"] == 3
    assert second["row_count"] == 3

    third = api.page(handle_id, second["next_page_token"])
    assert third["row_count"] == 1
    assert third["has_more"] is False
    assert third["next_page_token"] is None

    seen = {
        r["dataset_id"] for r in first["rows"] + second["rows"] + third["rows"]
    }
    assert len(seen) == 7


def test_page_token_cannot_be_forged_across_handles() -> None:
    api, _ = _api(rows=_aggregate_rows(5))
    a = api.query(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
        },
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        page_size=2,
    )
    b = api.query(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
        },
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        page_size=2,
    )
    with pytest.raises(lake_api.DuckLakeAPIError) as exc:
        api.page(b["handle_id"], a["next_page_token"])
    assert exc.value.reason_code == "ducklake_api.invalid_page_token"


def test_page_size_hard_cap() -> None:
    api, _ = _api()
    with pytest.raises(lake_api.DuckLakeAPIError) as exc:
        api.query(
            "ducklake.aggregate_count",
            {
                "tenant_id": TENANT,
                "catalog_id": CATALOG_ID,
                "dataset_id": "orders",
            },
            snapshot_id=_snapshot(),
            tenant_id=TENANT,
            page_size=lake_api.MAX_PAGE_SIZE + 1,
        )
    assert exc.value.reason_code == "ducklake_api.invalid_page_size"


def test_cancel_handle_is_idempotent() -> None:
    api, _ = _api(rows=_aggregate_rows(3))
    result = api.query(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
        },
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
    )
    handle_id = result["handle_id"]
    first = api.cancel(handle_id, reason="user_cancel")
    assert first["status"] == "ok"
    assert first["cancelled"] is True
    assert first["bounded"] is True
    second = api.cancel(handle_id, reason="user_cancel")
    assert second["idempotent_replay"] is True
    status = api.status(handle_id)
    assert status["cancelled"] is True


def test_cancellation_before_execution() -> None:
    api, _ = _api(rows=_aggregate_rows(10))
    token = qr.CancellationToken()
    token.cancel("client_abort")
    result = api.query(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
        },
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        cancellation=token,
    )
    assert result["handle_status"] == "cancelled"


def test_mcp_cancel_unknown_handle() -> None:
    api, _ = _api()
    result = dqt.ducklake_query_cancel("dlqh-" + "0" * 32, api=api)
    assert result["status"] == "error"
    assert result["reason_code"] == "ducklake_api.unknown_handle"


# ---------------------------------------------------------------------------
# Export digests
# ---------------------------------------------------------------------------


def test_export_returns_digests_not_sql_or_payload() -> None:
    api, _ = _api(rows=_aggregate_rows(2))
    result = api.export(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
            "row_limit": 2,
        },
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        format="json",
    )
    assert result["status"] == "ok"
    assert result["operation"] == "export"
    export = result["export"]
    assert export["content_digest"].startswith("sha256:")
    assert export["parameters_digest"].startswith("sha256:")
    assert export["root_cid"]
    assert export["row_count"] == 2
    assert export["read_only"] is True
    assert export["non_authoritative"] is True
    assert export["mutated_source"] is False
    assert export["reproducible"] is True
    assert export["bounded"] is True
    blob = str(result)
    assert "SELECT" not in blob
    assert "payload" not in export
    assert "private_key" not in blob


def test_export_is_byte_identical_for_same_snapshot_inputs() -> None:
    api, _ = _api(rows=_aggregate_rows(2))
    params = {
        "tenant_id": TENANT,
        "catalog_id": CATALOG_ID,
        "dataset_id": "orders",
        "row_limit": 2,
    }
    a = api.export(
        "ducklake.aggregate_count",
        params,
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        format="json",
    )
    b = api.export(
        "ducklake.aggregate_count",
        params,
        snapshot_id=_snapshot(),
        tenant_id=TENANT,
        format="json",
    )
    assert a["export"]["content_digest"] == b["export"]["content_digest"]
    assert a["export"]["parameters_digest"] == b["export"]["parameters_digest"]


def test_export_rejects_raw_sql() -> None:
    api, _ = _api()
    result = dqt.ducklake_export(
        "ducklake.aggregate_count",
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
        },
        snapshot_id=SNAPSHOT,
        tenant_id=TENANT,
        sql="COPY secrets TO 'out.csv'",
        api=api,
    )
    assert result["status"] == "error"
    assert result["reason_code"] == "query.sql_surface_denied"
    assert "COPY" not in result["error"]


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


def test_sanitize_strips_tokens_sql_paths_and_object_uris() -> None:
    cases = [
        "password=hunter2 token=abc123",
        "SELECT * FROM users WHERE token = 'quack_token_secret'",
        "failed opening /var/lib/ducklake/catalogs/a.duckdb",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.aaa.bbb",
        "s3://bucket/secret-path/key encryption_key=kms-xyz",
    ]
    for raw in cases:
        public = lake_api.sanitize_public_error(raw)
        assert public["status"] == "error"
        text = public["error"].lower()
        assert "hunter2" not in text
        assert "eyj" not in text
        assert "select" not in text
        assert "/var/lib" not in text
        assert "s3://" not in text
        assert "quack_token_secret" not in text


def test_redact_public_payload_scrubs_secret_keys() -> None:
    payload = {
        "catalog_id": CATALOG_ID,
        "quack_token": "super-secret-token",
        "encryption_key": "kms-material",
        "object_uri": "s3://bucket/path",
        "nested": {"password": "hunter2", "ok": "value"},
    }
    redacted = lake_api.redact_public_payload(payload)
    assert redacted["quack_token"] == "***REDACTED***"
    assert redacted["encryption_key"] == "***REDACTED***"
    assert redacted["object_uri"] == "***REDACTED***"
    assert redacted["nested"]["password"] == "***REDACTED***"
    assert redacted["nested"]["ok"] == "value"
    assert redacted["catalog_id"] == CATALOG_ID


# ---------------------------------------------------------------------------
# MCP tool surface
# ---------------------------------------------------------------------------


def test_mcp_discover_and_query_entrypoints() -> None:
    api, _ = _api(rows=_aggregate_rows(2))
    dqt.set_default_ducklake_api(api)
    try:
        catalogs = dqt.ducklake_discover_catalogs(tenant_id=TENANT)
        assert catalogs["status"] == "ok"
        assert catalogs["count"] >= 1

        datasets = dqt.ducklake_discover_datasets(
            catalog_id=CATALOG_ID, tenant_id=TENANT
        )
        assert datasets["status"] == "ok"

        snap = dqt.ducklake_select_snapshot(
            catalog_id=CATALOG_ID, snapshot_version=1, tenant_id=TENANT
        )
        assert snap["status"] == "ok"

        templates = dqt.ducklake_list_templates(trust="untrusted")
        assert templates["status"] == "ok"
        assert templates["count"] >= 1

        explained = dqt.ducklake_explain(
            "ducklake.aggregate_count",
            {
                "tenant_id": TENANT,
                "catalog_id": CATALOG_ID,
                "dataset_id": "orders",
            },
            snapshot_id=SNAPSHOT,
            tenant_id=TENANT,
        )
        assert explained["status"] == "ok"

        queried = dqt.ducklake_query(
            "ducklake.aggregate_count",
            {
                "tenant_id": TENANT,
                "catalog_id": CATALOG_ID,
                "dataset_id": "orders",
            },
            snapshot_id=SNAPSHOT,
            tenant_id=TENANT,
            page_size=1,
        )
        assert queried["status"] == "ok"
        assert queried["row_count"] == 1
        assert queried["has_more"] is True

        paged = dqt.ducklake_query_page(
            queried["handle_id"], queried["next_page_token"]
        )
        assert paged["status"] == "ok"

        status = dqt.ducklake_query_status(queried["handle_id"])
        assert status["status"] == "ok"

        cancelled = dqt.ducklake_query_cancel(queried["handle_id"])
        assert cancelled["cancelled"] is True

        exported = dqt.ducklake_export(
            "ducklake.aggregate_count",
            {
                "tenant_id": TENANT,
                "catalog_id": CATALOG_ID,
                "dataset_id": "orders",
            },
            snapshot_id=SNAPSHOT,
            tenant_id=TENANT,
        )
        assert exported["status"] == "ok"
        assert exported["export"]["content_digest"].startswith("sha256:")
    finally:
        dqt.set_default_ducklake_api(None)


def test_mcp_missing_template_returns_stable_code() -> None:
    api, _ = _api()
    missing = dqt.ducklake_query(api=api)
    assert missing["status"] == "error"
    assert missing["reason_code"] == "ducklake_api.missing_template_id"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_discover_catalogs_json() -> None:
    api, _ = _api()
    lake_api.set_default_api(api)
    try:
        code = lake_cli.run(
            ["--format", "json", "discover-catalogs", "--tenant-id", TENANT],
            api=api,
        )
        assert code == 0
    finally:
        lake_api.set_default_api(None)


def test_cli_query_and_export_commands() -> None:
    api, _ = _api(rows=_aggregate_rows(2))
    params = json.dumps(
        {
            "tenant_id": TENANT,
            "catalog_id": CATALOG_ID,
            "dataset_id": "orders",
            "row_limit": 2,
        }
    )
    query_result = lake_cli.run_command(
        lake_cli.build_parser().parse_args(
            [
                "--trust",
                "untrusted",
                "--tenant-id",
                TENANT,
                "query",
                "--template-id",
                "ducklake.aggregate_count",
                "--params",
                params,
                "--snapshot-id",
                SNAPSHOT,
                "--page-size",
                "2",
            ]
        ),
        api=api,
    )
    assert query_result.ok is True
    assert query_result.data["operation"] == "query"
    assert query_result.data["plane"] == lake_api.AccessPlane.PUBLICATION_PLANE.value

    export_result = lake_cli.run_command(
        lake_cli.build_parser().parse_args(
            [
                "--tenant-id",
                TENANT,
                "export",
                "--template-id",
                "ducklake.aggregate_count",
                "--params",
                params,
                "--snapshot-id",
                SNAPSHOT,
                "--export-format",
                "json",
            ]
        ),
        api=api,
    )
    assert export_result.ok is True
    assert export_result.data["export"]["content_digest"].startswith("sha256:")


def test_cli_rejects_sql_smuggled_params() -> None:
    api, _ = _api()
    result = lake_cli.run_command(
        lake_cli.build_parser().parse_args(
            [
                "--tenant-id",
                TENANT,
                "query",
                "--template-id",
                "ducklake.aggregate_count",
                "--params",
                json.dumps({"sql": "SELECT 1", "tenant_id": TENANT}),
                "--snapshot-id",
                SNAPSHOT,
            ]
        ),
        api=api,
    )
    assert result.ok is False
    assert result.exit_code == 2


def test_cli_text_format_is_bounded() -> None:
    api, _ = _api()
    result = lake_cli.run_command(
        lake_cli.build_parser().parse_args(
            ["discover-catalogs", "--tenant-id", TENANT]
        ),
        api=api,
    )
    text = lake_cli.format_output(result, fmt="text")
    assert "command=discover-catalogs" in text
    assert "ok=True" in text
    assert len(text.encode("utf-8")) <= lake_cli.MAX_TEXT_OUTPUT_BYTES


def test_cli_commands_cover_required_operations() -> None:
    required = {
        "discover-catalogs",
        "discover-datasets",
        "select-snapshot",
        "list-templates",
        "explain",
        "query",
        "page",
        "status",
        "cancel",
        "export",
    }
    assert required.issubset(set(lake_cli.COMMANDS))


def test_every_operation_is_template_bound() -> None:
    """Acceptance: every public operation reports an allowlisted template id."""

    api, _ = _api(rows=_aggregate_rows(1))
    ops = [
        api.discover_catalogs(tenant_id=TENANT),
        api.discover_datasets(catalog_id=CATALOG_ID, tenant_id=TENANT),
        api.select_snapshot(
            catalog_id=CATALOG_ID, snapshot_version=1, tenant_id=TENANT
        ),
        api.explain(
            "ducklake.aggregate_count",
            {
                "tenant_id": TENANT,
                "catalog_id": CATALOG_ID,
                "dataset_id": "orders",
            },
            snapshot_id=_snapshot(),
            tenant_id=TENANT,
        ),
        api.query(
            "ducklake.aggregate_count",
            {
                "tenant_id": TENANT,
                "catalog_id": CATALOG_ID,
                "dataset_id": "orders",
            },
            snapshot_id=_snapshot(),
            tenant_id=TENANT,
        ),
        api.export(
            "ducklake.aggregate_count",
            {
                "tenant_id": TENANT,
                "catalog_id": CATALOG_ID,
                "dataset_id": "orders",
            },
            snapshot_id=_snapshot(),
            tenant_id=TENANT,
        ),
    ]
    for result in ops:
        assert result["status"] == "ok"
        assert result.get("template_id")
        assert result.get("direct_authority_quack_access") is False
