"""CLI entry: ``python -m benchmarks.knowledge_graphs``."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .harness import run_profile
from .profiles import PROFILE_NAMES, get_profile, list_profiles
from .receipt import validate_receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m benchmarks.knowledge_graphs",
        description="Reproducible knowledge-graph load harness (KGP-029).",
    )
    parser.add_argument(
        "--profile",
        default="tiny",
        choices=list(PROFILE_NAMES),
        help="Named load profile (default: tiny, CI-mandatory).",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="Working directory for catalogs/stores/receipts.",
    )
    parser.add_argument(
        "--matrix-mode",
        default="ci",
        choices=("ci", "storage", "surface", "full"),
        help="How to expand surfaces × storage profiles.",
    )
    parser.add_argument(
        "--surfaces",
        nargs="*",
        default=None,
        help="Override surfaces (python cli mcp mcp_plus).",
    )
    parser.add_argument(
        "--storage-profiles",
        nargs="*",
        default=None,
        help="Override storage profiles.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="Path to write the versioned receipt JSON.",
    )
    parser.add_argument(
        "--list-profiles",
        action="store_true",
        help="List built-in profiles and exit.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full run result as JSON on stdout.",
    )
    args = parser.parse_args(argv)

    if args.list_profiles:
        for p in list_profiles(include_opt_in=True):
            flag = "opt-in" if p.opt_in else "mandatory"
            print(f"{p.name:20s} [{flag}] {p.description}")
        return 0

    profile = get_profile(args.profile)
    if profile.opt_in and args.profile != "tiny":
        print(
            f"note: profile {profile.name!r} is opt-in (long-running)",
            file=sys.stderr,
        )

    work_dir = args.work_dir
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="kg-load-"))
        print(f"work_dir={work_dir}", file=sys.stderr)

    result = run_profile(
        profile,
        work_dir=work_dir,
        matrix_mode=args.matrix_mode,
        surfaces=args.surfaces,
        storage_profiles=args.storage_profiles,
        receipt_path=args.receipt,
    )
    receipt = result.receipt.to_json_dict() if result.receipt else {}
    problems = validate_receipt(receipt) if receipt else ["no receipt"]
    if problems:
        print("receipt validation problems:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_json_dict(), indent=2, default=str))
    else:
        thr = receipt.get("throughput") or {}
        hist = receipt.get("latency_histogram") or {}
        print(f"status={result.status}")
        print(f"profile={profile.name} seed={profile.seed}")
        print(f"shape_fingerprint={result.graph.fingerprint}")
        print(
            f"nodes={result.graph.node_count} edges={result.graph.edge_count} "
            f"cells={len(result.cells)} elapsed_s={result.elapsed_s:.3f}"
        )
        print(
            f"throughput={thr.get('ops_per_s'):.2f} ops/s "
            f"ops={thr.get('operations')} "
            f"p50={hist.get('p50_ms'):.2f}ms "
            f"p95={hist.get('p95_ms'):.2f}ms "
            f"p99={hist.get('p99_ms'):.2f}ms"
        )
        print(f"receipt_id={receipt.get('receipt_id')}")
        print(f"digest={receipt.get('digest')}")
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
