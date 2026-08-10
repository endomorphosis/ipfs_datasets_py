#!/usr/bin/env python3
"""Ops CLI for the DQK-104 DuckDB + Quack catalog-owner service.

This tool plans, validates, and inspects hermetic catalog-owner configuration.
It **never** starts or promotes a production catalog endpoint and **never**
performs production DuckLake mutation. Activation remains held behind
DQK-088, DQK-094, and the signed DQK-102 gate.

Usage examples::

    python scripts/ops/ducklake_quack_catalog.py status
    python scripts/ops/ducklake_quack_catalog.py plan --catalog-id catalog_a
    python scripts/ops/ducklake_quack_catalog.py hermetic-validate
    python scripts/ops/ducklake_quack_catalog.py refuse-production
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

# Allow running from a worktree without an editable install.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ipfs_datasets_py.duckdb_control import quack_security as qs
from ipfs_datasets_py.ducklake import catalog as cat
from ipfs_datasets_py.ducklake import catalog_service as svc
from ipfs_datasets_py.ducklake import config as cfg
from ipfs_datasets_py.ducklake import quack_catalog as qc

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
        "boot_id": "boot-ops-001",
        "start_ticks": 1000,
        "cmdline_sha256": _CMDLINE,
    }
    payload.update(overrides)
    return cfg.ProcessBirthBinding(**payload)


def _profile(
    catalog_id: str = "catalog_a",
    *,
    port: int = 19001,
) -> cfg.CatalogShardProfile:
    return cfg.CatalogShardProfile(
        catalog_id=catalog_id,
        catalog_metadata=cfg.AuthorityDatabasePath(
            path=f"/var/lib/ducklake/catalogs/{catalog_id}.duckdb",
            storage_kind=cfg.AuthorityStorageKind.LOCAL_BLOCK,
            role="catalog",
            allowlist=_ALLOWLIST,
        ),
        companion_registry=cfg.AuthorityDatabasePath(
            path=f"/var/lib/ducklake/registries/{catalog_id}_registry.duckdb",
            storage_kind=cfg.AuthorityStorageKind.LOCAL_BLOCK,
            role="companion_registry",
            allowlist=_ALLOWLIST,
        ),
        quack_endpoint=cfg.QuackEndpointProfile(
            host="127.0.0.1",
            port=port,
            database=catalog_id,
            use_tls=True,
        ),
        owner_lease=cfg.OwnerLeaseBinding(
            lease_id=f"lease-{catalog_id}-1",
            owner_generation=1,
            fencing_epoch=1,
            process_birth=_birth(),
            endpoint_identity=f"quacks://127.0.0.1:{port}/{catalog_id}",
            os_identity=f"ducklake_{catalog_id}_owner",
        ),
        parquet_namespace=cfg.ParquetNamespace(
            namespace_id=f"{catalog_id}_ns",
            data_path=f"/var/lib/ducklake/data/{catalog_id}",
            staging_path=f"/var/lib/ducklake/staging/{catalog_id}",
            storage_kind=cfg.ParquetStorageKind.LOCAL,
            allowlist=_ALLOWLIST,
            provenance_cid_roots=("bafybeigdyrzt",),
        ),
        secret_profile=cfg.SecretProfile(
            quack_capability_ref=cfg.ExternalSecretReference(
                ref_id="vault:quack/broker",
                purpose="quack_capability",
                provider="vault",
            ),
            object_read_ref=cfg.ExternalSecretReference(
                ref_id="vault:obj/read",
                purpose="object_read",
            ),
            object_write_ref=cfg.ExternalSecretReference(
                ref_id="vault:obj/write",
                purpose="object_write",
            ),
            object_delete_ref=cfg.ExternalSecretReference(
                ref_id="vault:obj/delete",
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
        ),
    )


def _json_print(payload: Mapping[str, Any] | Sequence[Any] | Any) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    """Report activation gates and production denial posture."""

    return _json_print(
        {
            "task_id": "DQK-104",
            "implementation_generation": qc.IMPLEMENTATION_GENERATION,
            "activation": dict(qc.assert_activation_held()),
            "production_endpoint_enabled": qc.PRODUCTION_ENDPOINT_ENABLED,
            "production_mutation_enabled": qc.PRODUCTION_MUTATION_ENABLED,
            "activation_gates": list(qc.ACTIVATION_GATES),
            "extension_plan": dict(qc.build_extension_load_plan().as_mapping()),
            "templates": sorted(svc.ALLOWLISTED_TEMPLATES),
            "message": (
                "No production catalog endpoint is started or promoted by this "
                "tool. Activation remains held behind DQK-088, DQK-094, and the "
                "signed DQK-102 gate."
            ),
        }
    )


def cmd_plan(args: argparse.Namespace) -> int:
    """Emit a hermetic owner plan for one catalog shard (no network bind)."""

    profile = _profile(catalog_id=args.catalog_id, port=args.port)
    plan = {
        "catalog_id": profile.catalog_id,
        "catalog_path": profile.catalog_metadata.path,
        "companion_registry_path": profile.companion_registry.path,
        "storage_kind": profile.catalog_metadata.storage_kind.value,
        "quack_endpoint": dict(profile.quack_endpoint.as_mapping())
        if hasattr(profile.quack_endpoint, "as_mapping")
        else {
            "host": profile.quack_endpoint.host,
            "port": profile.quack_endpoint.port,
            "database": profile.quack_endpoint.database,
        },
        "owner_lease": dict(profile.owner_lease.as_mapping()),
        "extension_load_order": list(qc.build_extension_load_plan().load_order),
        "security_policy": dict(
            qc.default_owner_security_policy(
                catalog_path=profile.catalog_metadata.path,
                bind_host=profile.quack_endpoint.host,
                bind_port=profile.quack_endpoint.port,
                identity_label=profile.owner_lease.os_identity,
            ).to_dict()
        ),
        "production_endpoint": False,
        "production_mutation": False,
        "activation_gates": list(qc.ACTIVATION_GATES),
        "notes": [
            "DuckDB with the pinned DuckLake extension owns the catalog file",
            "Quack provides authenticated distributed transport only",
            "Companion registry is a separate private DatabaseInstance",
            "This plan does not bind a production listener",
        ],
    }
    return _json_print(plan)


def cmd_hermetic_validate(_args: argparse.Namespace) -> int:
    """Bootstrap an in-memory owner + run a bounded describe operation."""

    signing_key = "dqk-104-ops-hermetic-signing-key"
    service = svc.CatalogManagementService(signing_key=signing_key)
    profile = _profile(catalog_id="catalog_a", port=19001)
    owner = service.register_owner(profile, bootstrap=True)
    worker = cat.WorkerIdentity(
        worker_id="ops-worker-1",
        role=cfg.CatalogIdentityRole.WRITER,
        process_birth={
            "pid": 99,
            "boot_id": "boot-worker",
            "start_ticks": 50,
            "cmdline_sha256": _CMDLINE,
        },
        trusted=True,
    )
    result = service.submit(
        catalog_id="catalog_a",
        kind="catalog.describe",
        worker=worker,
        tenant_id="ops-tenant",
        caller_process_birth=dict(worker.process_birth),
    )
    # Prove publication profile is distinct.
    pub = qs.publication_gateway_policy(
        bind_host="127.0.0.1",
        bind_port=15433,
        identity_label="quack-publication-gateway",
    )
    owner.assert_distinct_from_publication(pub)
    payload = {
        "ok": True,
        "owner": dict(owner.as_mapping()),
        "result": dict(result.as_mapping()),
        "service": {
            "catalog_ids": list(service.catalog_ids()),
            "snapshot_vectors": {
                k: dict(v) for k, v in service.snapshot_vectors().items()
            },
        },
        "activation": dict(qc.assert_activation_held()),
        "production_endpoint_started": False,
    }
    service.stop_owner("catalog_a")
    return _json_print(payload)


def cmd_refuse_production(_args: argparse.Namespace) -> int:
    """Explicitly refuse production endpoint promotion and mutation."""

    errors: list[str] = []
    try:
        qc.assert_not_production_endpoint()
    except qc.ProductionEndpointDenied as exc:
        errors.append(str(exc))
    try:
        qc.assert_not_production_mutation()
    except qc.ActivationGateError as exc:
        errors.append(str(exc))
    try:
        qc.CatalogOwnerProcess(
            _profile(),
            signing_key="dqk-104-ops-hermetic-signing-key",
            production_mode=True,
        )
        errors.append("production_mode=True was unexpectedly accepted")
    except qc.ProductionEndpointDenied:
        pass
    return _json_print(
        {
            "refused": True,
            "production_endpoint_enabled": qc.PRODUCTION_ENDPOINT_ENABLED,
            "production_mutation_enabled": qc.PRODUCTION_MUTATION_ENABLED,
            "activation_gates": list(qc.ACTIVATION_GATES),
            "errors": errors,
            "message": (
                "Production catalog mutation remains disabled until DQK-088 "
                "and DQK-094 install governed ingestion and distributed "
                "logical-key reservations and the independently signed "
                "DQK-102 promotion gate authorizes the exact cutover."
            ),
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ducklake_quack_catalog",
        description=(
            "DQK-104 catalog-owner ops tool (hermetic plan/validate only; "
            "never starts a production endpoint)."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="Show activation gates and posture")
    p_status.set_defaults(func=cmd_status)

    p_plan = sub.add_parser("plan", help="Emit a hermetic owner plan")
    p_plan.add_argument("--catalog-id", default="catalog_a")
    p_plan.add_argument("--port", type=int, default=19001)
    p_plan.set_defaults(func=cmd_plan)

    p_val = sub.add_parser(
        "hermetic-validate",
        help="Bootstrap an in-memory owner and run a bounded describe",
    )
    p_val.set_defaults(func=cmd_hermetic_validate)

    p_ref = sub.add_parser(
        "refuse-production",
        help="Prove production endpoint/mutation remain refused",
    )
    p_ref.set_defaults(func=cmd_refuse_production)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except (qc.CatalogOwnerError, svc.CatalogServiceError, cat.CatalogError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
