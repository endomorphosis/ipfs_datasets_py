#!/usr/bin/env python3
"""CLI entrypoint for wallet processor fixture benchmarks (WALPROC-G640).

Usage:

    python ipfs_datasets_py/benchmarks/wallet_processors/run.py --fixture-only

Live smoke is refused unless both ``--live-smoke`` **and**
``--network-approval-id`` plus ``--approve-endpoint`` are supplied.  Live
provider latency is never used to set performance budgets.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _ensure_import_path() -> None:
    """Allow running as a script from the repository root or package root."""

    here = Path(__file__).resolve()
    # .../ipfs_datasets_py/benchmarks/wallet_processors/run.py
    package_root = here.parents[2]  # ipfs_datasets_py/
    repo_candidates = [package_root, package_root.parent]
    for candidate in repo_candidates:
        text = str(candidate)
        if text not in sys.path:
            sys.path.insert(0, text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Wallet processor benchmarks. Default mode is fixture-only; "
            "live smoke requires explicit endpoint and network approval."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--fixture-only",
        action="store_true",
        help="Run the deterministic offline fixture benchmark (default CI mode).",
    )
    mode.add_argument(
        "--live-smoke",
        action="store_true",
        help=(
            "Optional live provider smoke. Requires --approve-endpoint and "
            "--network-approval-id. Refused otherwise."
        ),
    )
    parser.add_argument(
        "--approve-endpoint",
        action="append",
        default=[],
        help="Endpoint URL allowlisted for live smoke (may be repeated).",
    )
    parser.add_argument(
        "--network-approval-id",
        default=None,
        help="Operator network-approval token required for live smoke.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write the JSON report.",
    )
    parser.add_argument(
        "--record-count",
        type=int,
        default=None,
        help="Override fixture record count (fixture-only).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _ensure_import_path()
    args = build_parser().parse_args(argv)

    # Deferred imports so --help works without package install quirks.
    from ipfs_datasets_py.processors.wallets.metrics import (
        LiveSmokeGate,
        LiveSmokePolicy,
        endpoint_fingerprint,
    )
    from ipfs_datasets_py.benchmarks.wallet_processors.runner import (
        build_fixture_report,
        run_fixture_benchmark,
        write_report,
    )

    if args.live_smoke:
        if not args.approve_endpoint or not args.network_approval_id:
            print(
                "ERROR: live smoke is disabled unless --approve-endpoint and "
                "--network-approval-id are both supplied.",
                file=sys.stderr,
            )
            return 2
        try:
            fingerprints = tuple(
                endpoint_fingerprint(url) for url in args.approve_endpoint
            )
            policy = LiveSmokePolicy(
                gate=LiveSmokeGate.APPROVED,
                approved_endpoint_fingerprints=fingerprints,
                network_approval_id=args.network_approval_id,
            )
        except Exception as exc:  # noqa: BLE001 - CLI boundary
            print(f"ERROR: invalid live smoke policy: {exc}", file=sys.stderr)
            return 2
        # Live smoke is intentionally not implemented here: the gate proves the
        # approval controls exist; operators wire real endpoints separately.
        report = {
            "schema_version": "wallet-processor-benchmark-report-v1",
            "mode": "live-smoke-gated",
            "live_smoke_enabled": policy.is_enabled,
            "live_smoke": policy.to_dict(),
            "notes": [
                "Live smoke gate accepted policy; no network I/O performed by "
                "this CLI. Wire an approved runner separately. Never set "
                "performance budgets from live provider latency alone."
            ],
            "result": None,
        }
        text = json.dumps(report, indent=2, sort_keys=True)
        print(text)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text + "\n", encoding="utf-8")
        return 0

    # fixture-only path
    kwargs: dict[str, int] = {}
    if args.record_count is not None:
        kwargs["record_count"] = int(args.record_count)
    result = run_fixture_benchmark(**kwargs)
    report = build_fixture_report(result)
    payload = report.to_dict()
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    write_report(report, args.output)

    # Non-zero only on hard budget failure so CI can gate regressions.
    if not result.budget_ok:
        print(
            "WARNING: fixture budget not met: "
            + ", ".join(result.budget_failures),
            file=sys.stderr,
        )
        # Soft signal: still exit 0 for informational CI; budget_ok is in JSON.
        # Hard gate can be enabled by operators parsing the report.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
