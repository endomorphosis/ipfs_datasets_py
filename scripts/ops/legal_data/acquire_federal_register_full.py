#!/usr/bin/env python3
"""Acquire the complete official cutoff-bound Federal Register inventory (LCR-052).

Enumerates FederalRegister.gov API result pages across non-overlapping date
partitions through the sealed UTC observation cutoff, records page/response
hashes, reconciles official totals against unique document-number identities,
resumes from atomic checkpoints, and writes the durable inventory receipt at
``docs/reports/legal_corpora_reindex/federal_inventory.json``.

Default CI operation is offline and network-free::

    python scripts/ops/legal_data/acquire_federal_register_full.py \
        --fixture-only --check

Live network acquisition is opt-in (``--live``) and never required for the
validation gate. Fixture mode expands a compact sealed recipe and proves:

* every partition/page is closed with stable response evidence;
* the identity union is duplicate-free by official ``legal_id``;
* no coverage gap, unexplained count drift, failed-final item, or secret.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.federal_register_acquisition import (  # noqa: E402
    GOAL_ID,
    SCHEMA_VERSION,
    TASK_ID,
    AcquisitionConfig,
    AcquisitionMode,
    FederalRegisterAcquisitionError,
    acquire_federal_register_inventory,
    atomic_create_json,
    atomic_write_json,
    build_compact_inventory_recipe,
    build_fixture_inventory_report,
    check_inventory_report,
    default_checkpoint_dir,
    default_report_path,
    expand_inventory_payload,
    inspect_inventory_report_structure,
    load_json_object,
    render_check_summary,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    DEFAULT_OBSERVATION_CUTOFF,
    LEGACY_DELTA_START_INCLUSIVE,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Acquire the cutoff-bound official Federal Register inventory "
            f"({TASK_ID} / {GOAL_ID}, schema {SCHEMA_VERSION}). "
            "Default fixture mode never contacts the network."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use the sealed offline fixture inventory (required for CI checks).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the frozen inventory report (or the fixture inventory "
            "when the report is missing under --fixture-only) against sealed "
            "acceptance."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the fixture inventory report to --report.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Path to the frozen inventory report "
            f"(default: {default_report_path(REPOSITORY_ROOT)})"
        ),
    )
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        default=None,
        help=(
            "Atomic checkpoint directory for resumable acquisition "
            "(default: $IPFS_ACCELERATE_AGENT_TASK_CHECKPOINT_DIR or "
            "repo-local .cache)."
        ),
    )
    parser.add_argument(
        "--observation-cutoff",
        default=DEFAULT_OBSERVATION_CUTOFF,
        help=(
            "Immutable UTC observation cutoff pin "
            f"(default: {DEFAULT_OBSERVATION_CUTOFF})."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Enable live FederalRegister.gov API acquisition. Never required "
            "for CI; incompatible with --fixture-only."
        ),
    )
    parser.add_argument(
        "--range-start",
        default=None,
        help="Inclusive publication-date range start (YYYY-MM-DD) for live mode.",
    )
    parser.add_argument(
        "--range-end",
        default=None,
        help="Inclusive publication-date range end (YYYY-MM-DD) for live mode.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the inventory report JSON to stdout.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore existing partition checkpoints.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path(REPOSITORY_ROOT)
    )
    checkpoint_dir = (
        Path(args.checkpoint_dir).expanduser().resolve()
        if args.checkpoint_dir is not None
        else default_checkpoint_dir(repo_root=REPOSITORY_ROOT)
    )

    try:
        if args.live and args.fixture_only:
            raise FederalRegisterAcquisitionError(
                "--live and --fixture-only are mutually exclusive"
            )

        if (args.check or args.write) and not args.fixture_only and not args.live:
            raise FederalRegisterAcquisitionError(
                "pass --fixture-only for the offline CI gate, or --live for "
                "network acquisition"
            )

        if args.fixture_only:
            # Fixture mode is fully deterministic and hermetic: never require
            # checkpoint I/O for CI --check / --write gates.
            fixture_report = build_fixture_inventory_report(
                observation_cutoff=args.observation_cutoff,
                checkpoint_dir=None,
            )
            recipe = build_compact_inventory_recipe(
                observation_cutoff=args.observation_cutoff,
            )

            raw_disk: Mapping[str, Any] | None = None
            if report_path.is_file():
                raw_disk = load_json_object(report_path)

            if args.write:
                # Prefer the compact admission-friendly recipe on disk; full
                # expansion is available via --print-json or runtime check.
                # Creation is a kernel-enforced no-replace operation so a
                # concurrent live receipt can never be overwritten.
                atomic_create_json(report_path, recipe)
                print(f"wrote inventory recipe: {report_path}", file=sys.stderr)
                raw_disk = recipe

            if args.check:
                fixture_result = check_inventory_report(fixture_report)
                if raw_disk is not None and raw_disk.get("mode") == "live":
                    live_structure = inspect_inventory_report_structure(
                        raw_disk,
                        require_live=True,
                    )
                    print(
                        "live_structure_valid="
                        f"{live_structure['structure_valid']} "
                        "live_authority_replayed=False authorizing=False "
                        f"digest={str(live_structure['inventory_digest'])[:12]}"
                    )
                    report = raw_disk
                    result = fixture_result
                elif raw_disk is not None:
                    result = check_inventory_report(raw_disk)
                    expanded = expand_inventory_payload(raw_disk)
                    disk_acceptance = dict(expanded.get("acceptance") or {})
                    fixture_acceptance = dict(fixture_report.get("acceptance") or {})
                    # Compare stable acceptance keys (ignore observed_at drift
                    # by projecting only sealed boolean/count fields).
                    stable_keys = (
                        "all_partitions_closed",
                        "all_pages_closed",
                        "duplicate_free_by_official_identity",
                        "no_coverage_gap",
                        "unexplained_count_drift",
                        "failed_final",
                        "failed_final_zero",
                        "secrets_absent",
                        "frontier_closed",
                        "completeness_oracle_passed",
                        "unique_document_count",
                        "enumerated",
                        "official_total",
                        "partition_count",
                        "observation_cutoff",
                        "range_start",
                        "range_end",
                        "mode",
                        "inventory_authority",
                        "previous_public_pin",
                        "all_expected_outputs_accounted",
                    )
                    disk_stable = {k: disk_acceptance.get(k) for k in stable_keys}
                    fixture_stable = {
                        k: fixture_acceptance.get(k) for k in stable_keys
                    }
                    if disk_stable != fixture_stable:
                        raise FederalRegisterAcquisitionError(
                            "on-disk report acceptance diverges from sealed fixture: "
                            f"disk={disk_stable} fixture={fixture_stable}"
                        )
                    report: Mapping[str, Any] = expanded
                else:
                    report = fixture_report
                    result = fixture_result
                print(render_check_summary(result))
                if args.print_json:
                    sys.stdout.write(
                        json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
                    )
                return 0

            if args.print_json:
                sys.stdout.write(
                    json.dumps(fixture_report, indent=2, sort_keys=True) + "\n"
                )
                return 0

            if args.write:
                return 0

            # Default fixture path: show sealed acceptance summary.
            check_inventory_report(fixture_report)
            print(
                render_check_summary(
                    {
                        "ok": True,
                        "acceptance": fixture_report["acceptance"],
                        "frontier_closed": True,
                        "inventory_digest": fixture_report.get("inventory_digest"),
                    }
                )
            )
            print(
                "hint: pass --fixture-only --check to validate the frozen report",
                file=sys.stderr,
            )
            return 0

        if args.live:
            range_start = args.range_start or LEGACY_DELTA_START_INCLUSIVE
            range_end = args.range_end
            if range_end is None:
                # Default live end is the observation cutoff calendar date.
                range_end = str(args.observation_cutoff)[:10]
            live_result = acquire_federal_register_inventory(
                config=AcquisitionConfig(
                    observation_cutoff=args.observation_cutoff,
                    range_start=range_start,
                    range_end=range_end,
                    mode=AcquisitionMode.LIVE,
                    resume=not args.no_resume,
                    checkpoint_dir=checkpoint_dir,
                )
            )
            if not live_result.frontier_closed:
                raise FederalRegisterAcquisitionError(
                    "live inventory acquisition failed to close: "
                    + "; ".join(live_result.errors[:8])
                )
            report = live_result.inventory_report
            validated: Mapping[str, Any] | None = None
            if args.write or args.check:
                validated = check_inventory_report(report, require_live=True)
            if args.write:
                # Persist only after an independent checkpoint-free replay.
                atomic_write_json(report_path, report)
                print(f"wrote inventory report: {report_path}", file=sys.stderr)
            if args.check:
                if validated is None:
                    raise FederalRegisterAcquisitionError(
                        "live validation result is unavailable"
                    )
                print(render_check_summary(validated))
            if args.print_json:
                sys.stdout.write(
                    json.dumps(dict(report), indent=2, sort_keys=True) + "\n"
                )
            elif not args.check:
                print(
                    render_check_summary(
                        {
                            "ok": True,
                            "acceptance": report["acceptance"],
                            "frontier_closed": True,
                            "inventory_digest": report.get("inventory_digest"),
                        }
                    )
                )
            return 0

        print(
            "error: pass --fixture-only (CI) or --live (network)",
            file=sys.stderr,
        )
        return 2
    except FederalRegisterAcquisitionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
