#!/usr/bin/env python3
"""CLI for the DQK-104 DuckDB + Quack catalog-owner service.

This script is an install/status/planning surface for the internal catalog
owner. Completing DQK-104 *implements* the owner service; it does **not**:

* start or promote a production catalog endpoint
* perform production DuckLake mutation
* authorize the DQK-102 cutover

Activation remains held behind DQK-088, DQK-094, and the signed DQK-102 gate.

Commands
--------
install-check
    Prove the catalog-owner implementation is importable and self-consistent
    without starting sockets or opening production catalogs.
status
    Report promotion-gate hold, template allowlist, and extension pin plan.
plan
    Emit a hermetic ownership plan for one catalog shard profile (JSON).
refuse-production
    Explicitly refuse production endpoint start / production mutation.
self-check
    Run an in-process bootstrap of a hermetic owner (no production bind).

Standard-library plus the repository package. Import side effects are limited
to path setup for hermetic and installed layouts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]


def _ensure_repo_on_path() -> None:
    root = str(REPO_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


_ensure_repo_on_path()

from ipfs_datasets_py.ducklake import catalog as cat  # noqa: E402
from ipfs_datasets_py.ducklake import catalog_service as cs  # noqa: E402
from ipfs_datasets_py.ducklake import config as cfg  # noqa: E402
from ipfs_datasets_py.ducklake import quack_catalog as qc  # noqa: E402


def _emit(payload: Mapping[str, Any] | Sequence[Any], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        if isinstance(payload, Mapping):
            for key, value in payload.items():
                print(f"{key}: {value}")
        else:
            print(payload)
    return 0


def _default_allowlist() -> tuple[str, ...]:
    return (
        "/var/lib/ducklake/catalogs",
        "/var/lib/ducklake/registries",
        "/var/lib/ducklake/data",
        "/var/lib/ducklake/staging",
    )


def _demo_profile(catalog_id: str = "catalog_a", port: int = 19001) -> cfg.CatalogShardProfile:
    allowlist = _default_allowlist()
    birth = cfg.ProcessBirthBinding(
        pid=4242,
        boot_id="boot-cli-001",
        start_ticks=1000,
        cmdline_sha256="sha256:" + ("11" * 32),
    )
    return cfg.CatalogShardProfile(
        catalog_id=catalog_id,
        catalog_metadata=cfg.AuthorityDatabasePath(
            path=f"/var/lib/ducklake/catalogs/{catalog_id}.duckdb",
            storage_kind=cfg.AuthorityStorageKind.LOCAL_BLOCK,
            role="catalog",
            allowlist=allowlist,
        ),
        companion_registry=cfg.AuthorityDatabasePath(
            path=f"/var/lib/ducklake/registries/{catalog_id}_registry.duckdb",
            storage_kind=cfg.AuthorityStorageKind.LOCAL_BLOCK,
            role="companion_registry",
            allowlist=allowlist,
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
            process_birth=birth,
            endpoint_identity=f"quacks://127.0.0.1:{port}/{catalog_id}",
            os_identity=f"ducklake_{catalog_id}_owner",
        ),
        parquet_namespace=cfg.ParquetNamespace(
            data_path=f"/var/lib/ducklake/data/{catalog_id}",
            storage_kind=cfg.ParquetStorageKind.LOCAL,
            namespace_id=f"{catalog_id}_ns",
            staging_path=f"/var/lib/ducklake/staging/{catalog_id}",
            allowlist=allowlist,
            provenance_cid_roots=("bafybeigdyrzt",),
        ),
        secret_profile=cfg.SecretProfile(
            quack_capability_ref=cfg.ExternalSecretReference(
                ref_id="vault:quack/catalog-a/broker",
                purpose="quack_capability",
                provider="vault",
            ),
            object_read_ref=cfg.ExternalSecretReference(
                ref_id="vault:obj/catalog-a/read",
                purpose="object_read",
            ),
            object_write_ref=cfg.ExternalSecretReference(
                ref_id="vault:obj/catalog-a/write",
                purpose="object_write",
            ),
            object_delete_ref=cfg.ExternalSecretReference(
                ref_id="vault:obj/catalog-a/delete",
                purpose="object_delete",
            ),
            catalog_encryption_key_ref=cfg.ExternalSecretReference(
                ref_id="kms:key/catalog-a",
                purpose="encryption_key",
                provider="kms",
            ),
            signing_key_ref=cfg.ExternalSecretReference(
                ref_id="kms:key/signing-a",
                purpose="signing_key",
                provider="kms",
            ),
        ),
    )


def cmd_install_check(args: argparse.Namespace) -> int:
    status = qc.promotion_gate_status()
    templates = [t.identity for t in qc.default_catalog_templates()]
    payload = {
        "task_id": "DQK-104",
        "installed": True,
        "production_endpoint_started": False,
        "production_mutation_enabled": False,
        "promotion_gate": dict(status),
        "template_identities": templates,
        "owner_extension_load_plan": dict(qc.owner_extension_load_plan()),
        "schema": qc.QUACK_CATALOG_SCHEMA,
        "service_schema": cs.CATALOG_SERVICE_SCHEMA,
        "creates_no_production_catalog_endpoint": True,
        "performs_no_production_ducklake_mutation": True,
    }
    return _emit(payload, as_json=args.json)


def cmd_status(args: argparse.Namespace) -> int:
    payload = {
        "promotion_gate": dict(qc.promotion_gate_status()),
        "templates": [
            dict(t.as_mapping()) for t in qc.default_catalog_templates()
        ],
        "owner_extension_load_plan": dict(qc.owner_extension_load_plan()),
        "forbidden_authority_catalogs": sorted(qc.FORBIDDEN_AUTHORITY_CATALOGS),
        "denied_sql_surfaces": sorted(qc.DENIED_SQL_SURFACES),
        "held_behind": list(qc.PROMOTION_GATE_HOLD),
    }
    return _emit(payload, as_json=args.json)


def cmd_plan(args: argparse.Namespace) -> int:
    profile = _demo_profile(catalog_id=args.catalog_id, port=args.port)
    service = cs.CatalogOwnerService(profile)
    payload = {
        "mode": "plan",
        "production_endpoint_started": False,
        "profile_catalog_id": profile.catalog_id,
        "catalog_path": profile.catalog_metadata.path,
        "companion_path": profile.companion_registry.path,
        "quack_endpoint": dict(profile.quack_endpoint.as_mapping()),
        "owner_lease": dict(profile.owner_lease.as_mapping()),
        "service_projection": dict(service.as_mapping()),
        "attach_plan": dict(
            cat.build_ducklake_attach_statement(profile).as_mapping()
        ),
        "notes": (
            "Plan only. No production endpoint is started and no production "
            "DuckLake mutation is performed. Activation remains held behind "
            "DQK-088, DQK-094, and the signed DQK-102 gate."
        ),
    }
    # Scrub any accidental secrets from the projection.
    cfg.assert_no_secrets_in_projection(payload)
    return _emit(payload, as_json=args.json)


def cmd_refuse_production(args: argparse.Namespace) -> int:
    try:
        if args.start_endpoint:
            qc.assert_no_production_activation(start_production_endpoint=True)
        if args.mutate:
            qc.assert_no_production_activation(perform_production_mutation=True)
        if not args.start_endpoint and not args.mutate:
            # Default: refuse both.
            qc.assert_no_production_activation(start_production_endpoint=True)
    except qc.PromotionGateHold as exc:
        payload = {
            "refused": True,
            "reason": str(exc),
            "held_behind": list(qc.PROMOTION_GATE_HOLD),
            "production_endpoint_started": False,
            "production_mutation_enabled": False,
        }
        return _emit(payload, as_json=args.json)
    # Should not succeed when flags request activation.
    return _emit(
        {
            "refused": False,
            "error": "expected promotion hold was not raised",
        },
        as_json=args.json,
    )


def cmd_self_check(args: argparse.Namespace) -> int:
    """Hermetic bootstrap of one owner without production bind."""

    profile = _demo_profile(catalog_id=args.catalog_id, port=args.port)
    service = cs.CatalogOwnerService(profile)
    acquired = service.acquire_ownership(bootstrap=True)
    proof = service.prove_single_selected_catalog()
    # Remote open must fail closed.
    remote_denied = False
    try:
        service.assert_remote_catalog_file_access_denied(action="open")
    except cat.CatalogAccessDenied:
        remote_denied = True
    shutdown = service.shutdown()
    payload = {
        "self_check": "ok",
        "acquired": dict(acquired),
        "single_catalog_proof": dict(proof),
        "remote_open_denied": remote_denied,
        "shutdown": dict(shutdown),
        "production_endpoint_started": False,
        "promotion_gate": dict(qc.promotion_gate_status()),
    }
    return _emit(payload, as_json=args.json)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "DQK-104 DuckDB + Quack catalog-owner CLI "
            "(no production endpoint; activation held behind DQK-088/094/102)"
        )
    )
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_install = sub.add_parser(
        "install-check",
        parents=[parent],
        help="Prove the catalog-owner implementation is installed",
    )
    p_install.set_defaults(func=cmd_install_check)

    p_status = sub.add_parser(
        "status", parents=[parent], help="Report gate hold and templates"
    )
    p_status.set_defaults(func=cmd_status)

    p_plan = sub.add_parser(
        "plan", parents=[parent], help="Emit a hermetic ownership plan"
    )
    p_plan.add_argument("--catalog-id", default="catalog_a")
    p_plan.add_argument("--port", type=int, default=19001)
    p_plan.set_defaults(func=cmd_plan)

    p_refuse = sub.add_parser(
        "refuse-production",
        parents=[parent],
        help="Refuse production endpoint start and/or mutation",
    )
    p_refuse.add_argument(
        "--start-endpoint",
        action="store_true",
        help="Attempt production endpoint start (must be refused)",
    )
    p_refuse.add_argument(
        "--mutate",
        action="store_true",
        help="Attempt production mutation (must be refused)",
    )
    p_refuse.set_defaults(func=cmd_refuse_production)

    p_self = sub.add_parser(
        "self-check",
        parents=[parent],
        help="Hermetic owner bootstrap without production bind",
    )
    p_self.add_argument("--catalog-id", default="catalog_a")
    p_self.add_argument("--port", type=int, default=19001)
    p_self.set_defaults(func=cmd_self_check)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except (qc.QuackCatalogError, cs.CatalogServiceError, cat.CatalogError, cfg.CatalogProfileError) as exc:
        err = {"error": type(exc).__name__, "message": str(exc)}
        print(json.dumps(err, indent=2, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
