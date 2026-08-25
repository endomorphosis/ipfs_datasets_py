#!/usr/bin/env python3
"""Check per-state state-law JSON-LD coverage and fail on gaps.

Usage:
  python scripts/ops/legal_data/check_state_law_coverage.py
  python scripts/ops/legal_data/check_state_law_coverage.py --min-records 20
  python scripts/ops/legal_data/check_state_law_coverage.py --states AL,AK,AZ

Production release gate (LCR-007):

  python scripts/ops/legal_data/check_state_law_coverage.py --production-release

A production release requires the exact 51-jurisdiction set (including DC) and
rejects one-row / subset success claims.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List, Sequence

ALL_STATES: List[str] = [
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
]
CANONICAL_PRODUCTION_JURISDICTIONS = frozenset(ALL_STATES)
EXPECTED_PRODUCTION_JURISDICTION_COUNT = 51
# One-row defaults were a false-success hazard; production requires depth.
PRODUCTION_MIN_RECORDS = 40


class SubsetReleaseError(ValueError):
    """Raised when coverage is asked to certify a subset as a production release."""


def reject_subset_release(
    states: Sequence[str],
    *,
    context: str = "production coverage check",
) -> List[str]:
    """Fail closed unless ``states`` is exactly the sealed 51-jurisdiction set."""
    normalized: List[str] = []
    seen = set()
    for item in states:
        code = str(item or "").strip().upper()
        if not code or code in seen:
            continue
        normalized.append(code)
        seen.add(code)
    observed = set(normalized)
    if observed != CANONICAL_PRODUCTION_JURISDICTIONS:
        missing = sorted(CANONICAL_PRODUCTION_JURISDICTIONS - observed)
        extra = sorted(observed - CANONICAL_PRODUCTION_JURISDICTIONS)
        raise SubsetReleaseError(
            f"subset release rejected for {context}: "
            f"count={len(observed)} (expected {EXPECTED_PRODUCTION_JURISDICTION_COUNT}); "
            f"missing={missing}; extra={extra}"
        )
    if "DC" not in observed:
        raise SubsetReleaseError(f"subset release rejected for {context}: DC is required")
    return normalized


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate state-law JSON-LD output coverage.")
    parser.add_argument(
        "--jsonld-dir",
        default=str(Path.home() / ".ipfs_datasets/state_laws/state_laws_jsonld"),
        help="Directory containing STATE-XX.jsonld files.",
    )
    parser.add_argument(
        "--states",
        default="all",
        help="Comma-separated state codes to validate, or 'all' (51 including DC).",
    )
    parser.add_argument(
        "--min-records",
        type=int,
        default=1,
        help="Minimum non-empty lines required per state file (diagnostic default).",
    )
    parser.add_argument(
        "--production-release",
        action="store_true",
        help=(
            "Production release gate: require exact 51 jurisdictions including DC "
            f"and min-records>={PRODUCTION_MIN_RECORDS} (rejects one-row/subset success)."
        ),
    )
    parser.add_argument(
        "--show-top",
        type=int,
        default=12,
        help="How many lowest-count states to print in summary.",
    )
    return parser.parse_args()


def _line_count(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if line.strip():
                count += 1
    return count


def main() -> int:
    args = parse_args()
    jsonld_dir = Path(args.jsonld_dir).expanduser().resolve()
    production = bool(args.production_release)
    min_records = max(0, int(args.min_records))
    if production:
        min_records = max(min_records, PRODUCTION_MIN_RECORDS)

    if str(args.states).strip().lower() == "all":
        states = list(ALL_STATES)
    else:
        requested = [s.strip().upper() for s in str(args.states).split(",") if s.strip()]
        states = [s for s in requested if s in ALL_STATES]
        invalid = [s for s in requested if s not in ALL_STATES]
        if invalid:
            print(f"Invalid state codes ignored: {', '.join(invalid)}")

    if production:
        try:
            states = reject_subset_release(states, context="check_state_law_coverage --production-release")
        except SubsetReleaseError as exc:
            print(f"subset_release: rejected")
            print(f"detail: {exc}")
            print("RESULT: FAIL")
            return 1

    counts: Dict[str, int] = {}
    missing: List[str] = []
    below_threshold: List[str] = []

    for state in states:
        fp = jsonld_dir / f"STATE-{state}.jsonld"
        if not fp.exists():
            counts[state] = 0
            missing.append(state)
            below_threshold.append(state)
            continue

        counts[state] = _line_count(fp)
        if counts[state] < min_records:
            below_threshold.append(state)

    low_sorted = sorted(counts.items(), key=lambda kv: kv[1])
    show_top = max(0, int(args.show_top))

    print(f"jsonld_dir: {jsonld_dir}")
    print(f"states_checked: {len(states)}")
    print(f"min_records: {min_records}")
    print(f"production_release: {production}")
    print(f"includes_dc: {'DC' in states}")
    print(f"missing_files: {len(missing)}")
    print(f"below_threshold: {len(below_threshold)}")

    if missing:
        print("missing_state_files:", ",".join(missing))
    if below_threshold:
        print("states_below_threshold:", ",".join(below_threshold))

    if show_top > 0:
        print("lowest_counts:")
        for state, count in low_sorted[:show_top]:
            print(f"  {state}: {count}")

    if production and (missing or below_threshold or len(states) != EXPECTED_PRODUCTION_JURISDICTION_COUNT):
        print("RESULT: FAIL")
        return 1

    if missing or below_threshold:
        print("RESULT: FAIL")
        return 1

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
