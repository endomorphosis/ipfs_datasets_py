#!/usr/bin/env python3
"""USPTO CLI — status, sync-public, import-private, analyze, preflight, explain.

Credentials are accepted only as *references* (``--credential-ref``), never as
secret values. Private import requires ``--tenant``, ``--path``, and
``--classification``. No subcommand signs, pays, files, or automates a browser.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

__all__ = [
    "COMMANDS",
    "FORBIDDEN_COMMANDS",
    "create_parser",
    "main",
]

COMMANDS: tuple[str, ...] = (
    "status",
    "sync-public",
    "import-private",
    "analyze",
    "preflight",
    "explain",
)

FORBIDDEN_COMMANDS: frozenset[str] = frozenset(
    {
        "sign",
        "pay",
        "file",
        "submit",
        "browser",
        "scrape",
        "login",
        "automate-browser",
        "mfa",
    }
)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets uspto",
        description=(
            "USPTO public status/sync, authorized private import, analyze, "
            "preflight, and explain. Credentials by reference only; "
            "no sign/pay/file/browser automation."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON contract payloads on stdout.",
    )
    parser.add_argument(
        "--credential-ref",
        default="",
        help="Credential *reference id* only (never a secret value).",
    )
    parser.add_argument(
        "--api-key-ref",
        default="",
        dest="api_key_ref",
        help="Alias of --credential-ref (reference id only).",
    )

    sub = parser.add_subparsers(dest="command", help="USPTO operation")

    # status
    p_status = sub.add_parser(
        "status",
        help="Fetch/normalize public application status (canonical contract).",
    )
    p_status.add_argument(
        "--application-number",
        required=True,
        help="USPTO application number.",
    )
    p_status.add_argument("--matter-id", default="", help="Optional matter id.")
    p_status.add_argument(
        "--force-refresh",
        action="store_true",
        help="Bypass cached status snapshot.",
    )
    p_status.add_argument(
        "--fixture-recipe",
        default="",
        help="Optional recorded ODP HTTP recipe path (offline).",
    )

    # sync-public
    p_sync = sub.add_parser(
        "sync-public",
        help="Synchronize public status and document inventory/bytes.",
    )
    p_sync.add_argument("--application-number", required=True)
    p_sync.add_argument("--matter-id", default="")
    p_sync.add_argument("--force-refresh", action="store_true")
    p_sync.add_argument(
        "--no-documents",
        action="store_true",
        help="Skip document inventory/byte sync.",
    )
    p_sync.add_argument(
        "--fixture-recipe",
        default="",
        help="Optional recorded ODP HTTP recipe path (offline).",
    )

    # import-private
    p_imp = sub.add_parser(
        "import-private",
        help=(
            "Import an authorized local Patent Center export. "
            "Requires tenant, path, and classification."
        ),
    )
    p_imp.add_argument(
        "--tenant",
        required=True,
        help="Tenant id bound to the private store (required).",
    )
    p_imp.add_argument(
        "--path",
        required=True,
        help="Authorized import root path (required).",
    )
    p_imp.add_argument(
        "--classification",
        required=True,
        help=(
            "Disclosure classification for the import boundary "
            "(e.g. confidential_application)."
        ),
    )
    p_imp.add_argument(
        "--manifest",
        required=True,
        help="Path to export_manifest.json or fixture directory.",
    )
    p_imp.add_argument(
        "--authorization",
        required=True,
        help="Path to import authorization JSON.",
    )
    p_imp.add_argument(
        "--store-root",
        default="",
        help="Private encrypted store root (required for durable import).",
    )
    p_imp.add_argument(
        "--tenant-key-file",
        default="",
        help="Path to tenant key material (never printed).",
    )
    p_imp.add_argument("--fail-fast", action="store_true")

    # analyze
    p_an = sub.add_parser(
        "analyze",
        help="Assemble analysis bundle / dossier from inputs.",
    )
    p_an.add_argument("--matter-id", default="", help="Matter identifier.")
    p_an.add_argument(
        "--bundle-json",
        default="",
        help="Path to UsptoAnalysisBundle JSON.",
    )
    p_an.add_argument(
        "--seed-classification",
        default="public_user",
        help="Seed disclosure classification (default: public_user).",
    )

    # preflight
    p_pf = sub.add_parser(
        "preflight",
        help="Run package preflight (never signs, pays, or files).",
    )
    p_pf.add_argument(
        "--package-json",
        required=True,
        help="Path to PreflightPackageInput JSON.",
    )

    # explain
    p_ex = sub.add_parser(
        "explain",
        help="Render explainable requirement/evidence gap report.",
    )
    p_ex.add_argument(
        "--bundle-json",
        default="",
        help="Path to UsptoAnalysisBundle JSON.",
    )
    p_ex.add_argument(
        "--gap-report-json",
        default="",
        help="Path to existing RequirementEvidenceGapReport JSON.",
    )
    p_ex.add_argument("--matter-id", default="")
    p_ex.add_argument("--analysis-id", default="")

    return parser


def _load_json(path: str | Path) -> Any:
    p = Path(path)
    with p.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _emit(payload: Any, *, as_json: bool) -> int:
    if hasattr(payload, "to_dict") and callable(payload.to_dict):
        data = payload.to_dict()
    elif isinstance(payload, Mapping):
        data = dict(payload)
    else:
        data = {"result": str(payload)}
    from ipfs_datasets_py.processors.domains.uspto.api import scrub_credential_fields

    data = scrub_credential_fields(data)
    if as_json:
        print(json.dumps(data, indent=2, sort_keys=True, default=str))
    else:
        print(json.dumps(data, indent=2, sort_keys=True, default=str))
    return 0


def _credential_ref_from_args(args: argparse.Namespace):
    from ipfs_datasets_py.processors.domains.uspto.api import CredentialRef

    ref = (getattr(args, "credential_ref", None) or "") or (
        getattr(args, "api_key_ref", None) or ""
    )
    ref = str(ref).strip()
    if not ref:
        return None
    return CredentialRef(reference_id=ref)


def _build_client_from_fixture(recipe_path: str):
    from ipfs_datasets_py.processors.domains.uspto.providers.base import ApiKeySecret
    from ipfs_datasets_py.processors.domains.uspto.providers.patent_file_wrapper import (
        PatentFileWrapperClient,
    )

    # Test/offline key is an ApiKeySecret with a reference — not a CLI secret arg.
    secret = ApiKeySecret("test-key-not-a-secret", reference_id="cli-fixture-key")
    return PatentFileWrapperClient.from_recorded_recipe(recipe_path, api_key=secret)


def _cmd_status(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.processors.domains.uspto.api import USPTOAnalysisAPI

    client = None
    if args.fixture_recipe:
        client = _build_client_from_fixture(args.fixture_recipe)
    api = USPTOAnalysisAPI(
        client=client,
        credential_ref=_credential_ref_from_args(args),
    )
    result = api.status(
        args.application_number,
        matter_id=args.matter_id or None,
        force_refresh=bool(args.force_refresh),
        credential_ref=_credential_ref_from_args(args),
    )
    return _emit(result, as_json=bool(args.json))


def _cmd_sync_public(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.processors.domains.uspto.api import USPTOAnalysisAPI

    client = None
    if args.fixture_recipe:
        client = _build_client_from_fixture(args.fixture_recipe)
    api = USPTOAnalysisAPI(
        client=client,
        credential_ref=_credential_ref_from_args(args),
    )
    result = api.sync_public(
        args.application_number,
        matter_id=args.matter_id or None,
        force_refresh=bool(args.force_refresh),
        sync_documents=not bool(args.no_documents),
        credential_ref=_credential_ref_from_args(args),
    )
    return _emit(result, as_json=bool(args.json))


def _cmd_import_private(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.processors.domains.uspto.api import USPTOAnalysisAPI, UsptoAPIError
    from ipfs_datasets_py.processors.domains.uspto.private_store import (
        PrivateArtifactStore,
        TenantKeyMaterial,
        generate_tenant_key,
    )
    from ipfs_datasets_py.processors.domains.uspto.providers.patent_center_export import (
        ExportManifest,
        ImportAuthorization,
        load_fixture_authorization,
        load_fixture_manifest,
    )

    tenant = str(args.tenant).strip()
    import_path = Path(args.path).expanduser()
    classification = str(args.classification).strip()
    if not tenant or not classification:
        raise UsptoAPIError(
            "import-private requires --tenant, --path, and --classification",
            code="missing_private_import_args",
        )

    # Load manifest
    manifest_path = Path(args.manifest)
    if manifest_path.is_dir():
        manifest = load_fixture_manifest(manifest_path)
    else:
        manifest = ExportManifest.from_dict(_load_json(manifest_path))

    # Load authorization
    auth_path = Path(args.authorization)
    if auth_path.is_dir():
        authorization = load_fixture_authorization(
            auth_path, import_root=import_path, tenant_id=tenant
        )
    else:
        authorization = ImportAuthorization.from_dict(_load_json(auth_path))
        # Ensure tenant alignment when CLI tenant is authoritative.
        if authorization.tenant_id != tenant:
            raise UsptoAPIError(
                "authorization tenant_id does not match --tenant",
                code="tenant_mismatch",
            )

    store_root = args.store_root or str(import_path / ".private_store")
    if args.tenant_key_file:
        # Key file path is a reference to material on disk — content never printed.
        key_bytes = Path(args.tenant_key_file).read_bytes()
        tenant_key = TenantKeyMaterial(tenant_id=tenant, key_bytes=key_bytes)
    else:
        tenant_key = generate_tenant_key(tenant)
    store = PrivateArtifactStore(store_root, tenant_key)
    api = USPTOAnalysisAPI(private_store=store)
    result = api.import_private(
        tenant_id=tenant,
        import_path=import_path,
        classification=classification,
        authorization=authorization,
        manifest=manifest,
        fail_fast=bool(args.fail_fast),
    )
    return _emit(result, as_json=bool(args.json))


def _cmd_analyze(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.processors.domains.uspto.api import USPTOAnalysisAPI
    from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
        UsptoAnalysisBundle,
    )

    api = USPTOAnalysisAPI()
    bundle = None
    if args.bundle_json:
        bundle = UsptoAnalysisBundle.from_dict(_load_json(args.bundle_json))
    result = api.analyze(
        matter_id=args.matter_id or None,
        analysis_bundle=bundle,
        seed_classification=args.seed_classification,
    )
    return _emit(result, as_json=bool(args.json))


def _cmd_preflight(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.processors.domains.uspto.api import USPTOAnalysisAPI
    from ipfs_datasets_py.processors.domains.uspto.workflow_processor import (
        PreflightPackageInput,
    )

    api = USPTOAnalysisAPI()
    package = PreflightPackageInput.from_dict(_load_json(args.package_json))
    result = api.preflight(package)
    return _emit(result, as_json=bool(args.json))


def _cmd_explain(args: argparse.Namespace) -> int:
    from ipfs_datasets_py.processors.domains.uspto.api import USPTOAnalysisAPI, UsptoAPIError
    from ipfs_datasets_py.processors.domains.uspto.analysis.analysis_bundle import (
        UsptoAnalysisBundle,
    )
    from ipfs_datasets_py.processors.domains.uspto.analysis.gap_report import (
        RequirementEvidenceGapReport,
    )

    api = USPTOAnalysisAPI()
    gap_report = None
    bundle = None
    if args.gap_report_json:
        gap_report = RequirementEvidenceGapReport.from_dict(
            _load_json(args.gap_report_json)
        )
    if args.bundle_json:
        bundle = UsptoAnalysisBundle.from_dict(_load_json(args.bundle_json))
    if gap_report is None and bundle is None:
        raise UsptoAPIError(
            "explain requires --bundle-json or --gap-report-json",
            code="missing_explain_input",
        )
    result = api.explain(
        analysis_bundle=bundle,
        gap_report=gap_report,
        matter_id=args.matter_id or None,
        analysis_id=args.analysis_id or None,
    )
    return _emit(result, as_json=bool(args.json))


_HANDLERS = {
    "status": _cmd_status,
    "sync-public": _cmd_sync_public,
    "import-private": _cmd_import_private,
    "analyze": _cmd_analyze,
    "preflight": _cmd_preflight,
    "explain": _cmd_explain,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.command:
        parser.print_help()
        return 2

    cmd = str(args.command).strip().lower()
    if cmd in FORBIDDEN_COMMANDS:
        print(
            json.dumps(
                {
                    "error": "forbidden_command",
                    "command": cmd,
                    "message": "USPTO CLI never signs, pays, files, or automates a browser",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    # Reject secret-style flags if a user somehow injects them via unknown args
    # (argparse already rejects unknowns; keep explicit guard for help text).
    if any(
        flag in (argv or [])
        for flag in (
            "--api-key",
            "--password",
            "--secret",
            "--token",
            "--cookie",
            "--session",
        )
    ):
        print(
            json.dumps(
                {
                    "error": "credential_argument_forbidden",
                    "message": "credentials must be references (--credential-ref), not secret values",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    handler = _HANDLERS.get(cmd)
    if handler is None:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    try:
        return int(handler(args))
    except Exception as exc:
        err = {
            "error": type(exc).__name__,
            "message": str(exc),
            "code": getattr(exc, "code", None),
        }
        print(json.dumps(err, sort_keys=True, default=str), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
