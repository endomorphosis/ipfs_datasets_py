"""CLI: python -m benchmarks.knowledge_graphs.soak --profile short"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmarks.knowledge_graphs.safety import BenchmarkSafetyError
from benchmarks.knowledge_graphs.soak.profiles import PROFILE_NAMES, get_soak_profile
from benchmarks.knowledge_graphs.soak.runner import run_soak, write_soak_receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run a knowledge-graph soak profile (KGP-031)."
    )
    parser.add_argument(
        "--profile",
        default="short",
        choices=list(PROFILE_NAMES) + ["24h", "ci"],
        help="Soak profile name (default: short).",
    )
    parser.add_argument(
        "--work-dir",
        default=None,
        help="Optional directory for receipt output.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full result JSON to stdout.",
    )
    parser.add_argument(
        "--skip-short-gate",
        action="store_true",
        help="Do not auto-run short profiles before opt-in profiles.",
    )
    args = parser.parse_args(argv)

    profile = get_soak_profile(args.profile)
    try:
        result = run_soak(
            profile,
            work_dir=args.work_dir,
            require_short_first=not args.skip_short_gate,
            short_already_passed=args.skip_short_gate,
        )
    except BenchmarkSafetyError as exc:
        print(f"refusing unsafe soak: {exc}", file=sys.stderr)
        return 2
    if args.work_dir:
        out = Path(args.work_dir) / f"soak-{profile.name}-latest.json"
        write_soak_receipt(result.receipt, out)
        print(f"wrote {out}", file=sys.stderr)

    if args.json:
        print(json.dumps(result.to_json_dict(), indent=2, sort_keys=True))
    else:
        print(
            f"profile={result.profile.name} status={result.status} "
            f"elapsed_s={result.elapsed_s:.3f} ops={result.operations} "
            f"growth_ok={result.growth.ok} summary={result.growth.summary}"
        )
    return 0 if result.status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
