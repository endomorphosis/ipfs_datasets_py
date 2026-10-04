#!/usr/bin/env python3
"""Bounded CLI for wallet processor ingest/export surfaces (WALPROC-G610).

Thin adapter over :class:`~ipfs_datasets_py.processors.wallets.api.WalletProcessorAPI`.
Commands never sign or broadcast; every scan requires finite bounds.

Usage:
    python -m ipfs_datasets_py.cli.wallets <command> [options]
    ipfs-datasets wallets <command> [options]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from ipfs_datasets_py.processors.wallets.api import (
    CapabilitiesRequest,
    ExportMode,
    LedgerRangeIngestRequest,
    ResumeRequest,
    ScanBounds,
    StatusRequest,
    TrustLevel,
    TrustPolicy,
    VerifyManifestRequest,
    WalletExportRequest,
    WalletIngestRequest,
    WalletProcessorAPI,
)
from ipfs_datasets_py.processors.wallets.export import ExportFormat
from ipfs_datasets_py.processors.wallets.models import (
    ChainRef,
    RawPayloadPolicy,
)


def _chain_from_args(args: argparse.Namespace) -> ChainRef:
    return ChainRef(
        namespace=args.chain_namespace,
        network=args.chain_network,
        chain_id=args.chain_id,
        genesis_hash=args.genesis_hash,
    )


def _bounds_from_args(args: argparse.Namespace) -> ScanBounds:
    return ScanBounds(
        max_items=args.max_items,
        max_pages=args.max_pages,
        max_requests=args.max_requests,
        max_response_bytes=args.max_response_bytes,
        max_time_seconds=args.max_time_seconds,
        max_retries=args.max_retries,
    )


def _add_bound_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--max-items", type=int, default=1_000)
    parser.add_argument("--max-pages", type=int, default=100)
    parser.add_argument("--max-requests", type=int, default=100)
    parser.add_argument(
        "--max-response-bytes", type=int, default=16 * 1024 * 1024
    )
    parser.add_argument("--max-time-seconds", type=float, default=300.0)
    parser.add_argument("--max-retries", type=int, default=3)


def _add_chain_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--chain-namespace", required=True)
    parser.add_argument("--chain-network", required=True)
    parser.add_argument("--chain-id", required=True)
    parser.add_argument("--genesis-hash", required=True)


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets wallets",
        description=(
            "Bounded wallet processor CLI (ingest/export/resume/status/"
            "capabilities/verify). No signing or broadcast."
        ),
    )
    parser.add_argument(
        "--trust",
        choices=[t.value for t in TrustLevel],
        default=TrustLevel.TRUSTED.value,
        help="Caller trust level (MCP adapters force untrusted).",
    )
    parser.add_argument(
        "--allowed-provider-host",
        action="append",
        default=[],
        dest="allowed_provider_hosts",
        help="Allowlisted provider host for untrusted mode (repeatable).",
    )
    parser.add_argument(
        "--allowed-secret-prefix",
        action="append",
        default=[],
        dest="allowed_secret_prefixes",
        help="Allowlisted secret reference prefix for untrusted mode.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # list-families
    sub.add_parser(
        "list-families",
        help="List registered processor families without loading chain extras",
    )

    # capabilities
    caps = sub.add_parser("capabilities", help="Show declared capabilities")
    caps.add_argument("--family")
    caps.add_argument("--network")

    # ingest
    ingest = sub.add_parser("ingest", help="Bounded wallet-centric ingest")
    ingest.add_argument("--scope", required=True, help="Wallet/account scope")
    _add_chain_flags(ingest)
    _add_bound_flags(ingest)
    ingest.add_argument("--family")
    ingest.add_argument("--cursor")
    ingest.add_argument("--provider-url")
    ingest.add_argument("--secret-reference")
    ingest.add_argument("--export-dir")
    ingest.add_argument(
        "--export-format",
        action="append",
        dest="export_formats",
        default=[],
        choices=[f.value for f in ExportFormat],
    )
    ingest.add_argument(
        "--store-raw-payloads",
        action="store_true",
        help="Explicit opt-in for raw payload storage",
    )
    ingest.add_argument("--safety-depth", type=int, default=0)
    ingest.add_argument("--request-id")

    # ledger-ingest
    ledger = sub.add_parser(
        "ledger-ingest", help="Bounded finite ledger-range ingest"
    )
    ledger.add_argument("--scope", required=True)
    _add_chain_flags(ledger)
    _add_bound_flags(ledger)
    ledger.add_argument("--start-position", type=int, required=True)
    ledger.add_argument("--end-position", type=int, required=True)
    ledger.add_argument("--family")
    ledger.add_argument("--cursor")
    ledger.add_argument("--provider-url")
    ledger.add_argument("--secret-reference")
    ledger.add_argument("--export-dir")
    ledger.add_argument(
        "--export-format",
        action="append",
        dest="export_formats",
        default=[],
        choices=[f.value for f in ExportFormat],
    )
    ledger.add_argument("--store-raw-payloads", action="store_true")
    ledger.add_argument("--safety-depth", type=int, default=0)
    ledger.add_argument("--request-id")

    # export
    export = sub.add_parser(
        "export",
        help="Export records (default mode=finalized; provisional/raw explicit)",
    )
    export.add_argument("--scope", required=True)
    _add_chain_flags(export)
    _add_bound_flags(export)
    export.add_argument("--output-dir", required=True)
    export.add_argument(
        "--mode",
        choices=[m.value for m in ExportMode],
        default=ExportMode.FINALIZED.value,
    )
    export.add_argument(
        "--format",
        action="append",
        dest="formats",
        default=[],
        choices=[f.value for f in ExportFormat],
    )
    export.add_argument(
        "--raw-payload-policy",
        choices=[p.value for p in RawPayloadPolicy],
        default=RawPayloadPolicy.OMITTED.value,
    )
    export.add_argument(
        "--records-jsonl",
        help="Optional JSONL file of already-normalized record dicts",
    )
    export.add_argument("--request-id")

    # resume
    resume = sub.add_parser("resume", help="Resume a prior job by id")
    resume.add_argument("--job-id", required=True)
    _add_bound_flags(resume)
    resume.add_argument("--request-id")

    # status
    status = sub.add_parser("status", help="Sanitized job status receipt")
    status.add_argument("--job-id", required=True)

    # verify-manifest
    verify = sub.add_parser("verify-manifest", help="Verify export manifest")
    verify.add_argument("--path", required=True)

    return parser


def _build_api(args: argparse.Namespace) -> WalletProcessorAPI:
    policy = TrustPolicy(
        allowed_provider_hosts=frozenset(args.allowed_provider_hosts or ()),
        allowed_secret_prefixes=frozenset(args.allowed_secret_prefixes or ()),
    )
    return WalletProcessorAPI(
        trust_policy=policy,
        trust=TrustLevel(args.trust),
    )


def _print_json(payload: Any) -> int:
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return 0


def _load_records(path: str | None) -> tuple[object, ...]:
    if not path:
        return ()
    import json as _json

    records: list[object] = []
    text = Path(path).read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        records.append(_json.loads(line))
    return tuple(records)


async def _dispatch(args: argparse.Namespace) -> int:
    api = _build_api(args)
    cmd = args.command

    if cmd == "list-families":
        return _print_json(api.list_families().to_dict())

    if cmd == "capabilities":
        result = api.capabilities(
            CapabilitiesRequest(family=args.family, network=args.network)
        )
        return _print_json(result.to_dict())

    if cmd == "ingest":
        formats = tuple(ExportFormat(f) for f in (args.export_formats or ()))
        request = WalletIngestRequest(
            scope=args.scope,
            chain=_chain_from_args(args),
            bounds=_bounds_from_args(args),
            family=args.family,
            request_id=args.request_id,
            cursor=args.cursor,
            provider_url=args.provider_url,
            secret_reference=args.secret_reference,
            export_formats=formats,
            export_dir=args.export_dir,
            store_raw_payloads=bool(args.store_raw_payloads),
            safety_depth=args.safety_depth,
        )
        result = await api.wallet_ingest(request)
        return _print_json(result.to_dict())

    if cmd == "ledger-ingest":
        formats = tuple(ExportFormat(f) for f in (args.export_formats or ()))
        request = LedgerRangeIngestRequest(
            scope=args.scope,
            chain=_chain_from_args(args),
            start_position=args.start_position,
            end_position=args.end_position,
            bounds=_bounds_from_args(args),
            family=args.family,
            request_id=args.request_id,
            cursor=args.cursor,
            provider_url=args.provider_url,
            secret_reference=args.secret_reference,
            export_formats=formats,
            export_dir=args.export_dir,
            store_raw_payloads=bool(args.store_raw_payloads),
            safety_depth=args.safety_depth,
        )
        result = await api.ledger_ingest(request)
        return _print_json(result.to_dict())

    if cmd == "export":
        formats = tuple(
            ExportFormat(f) for f in (args.formats or [ExportFormat.JSONL.value])
        )
        request = WalletExportRequest(
            scope=args.scope,
            chain=_chain_from_args(args),
            output_dir=args.output_dir,
            bounds=_bounds_from_args(args),
            request_id=args.request_id,
            records=_load_records(args.records_jsonl),
            formats=formats,
            mode=ExportMode(args.mode),
            raw_payload_policy=RawPayloadPolicy(args.raw_payload_policy),
        )
        result = await api.wallet_export(request)
        return _print_json(result.to_dict())

    if cmd == "resume":
        result = await api.resume(
            ResumeRequest(
                job_id=args.job_id,
                bounds=_bounds_from_args(args),
                request_id=args.request_id,
            )
        )
        return _print_json(result.to_dict())

    if cmd == "status":
        receipt = api.status(StatusRequest(job_id=args.job_id))
        return _print_json(receipt.to_dict())

    if cmd == "verify-manifest":
        result = api.verify_manifest(VerifyManifestRequest(path=args.path))
        return _print_json(result.to_dict())

    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


def main(argv: Sequence[str] | None = None) -> int:
    parser = create_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    # Refuse to expose signing verbs even if someone aliases them later.
    if args.command in WalletProcessorAPI.FORBIDDEN_OPERATIONS:
        print(
            f"command {args.command!r} is not supported: "
            "wallet processors never sign or broadcast",
            file=sys.stderr,
        )
        return 2
    try:
        return asyncio.run(_dispatch(args))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "error",
                    "error": type(exc).__name__,
                    "message": str(exc),
                },
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
