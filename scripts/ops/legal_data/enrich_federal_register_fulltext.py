#!/usr/bin/env python3
"""Acquire official Federal Register body text and classify dispositions (LCR-053).

Reads the closed LCR-052 inventory (never rewriting it), fetches official
HTML/XML/PDF/GovInfo locators in source-precedence order, detects
anti-bot/navigation/error/placeholder content, and writes the typed
coverage receipt at
``docs/reports/legal_corpora_reindex/federal_fulltext_coverage.json``.

Default CI operation is offline and network-free::

    python scripts/ops/legal_data/enrich_federal_register_fulltext.py \
        --fixture-only --check

Live network full-text crawling is opt-in (``--live``) and never required
for the validation gate.
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

from ipfs_datasets_py.processors.legal_data.federal_register_fulltext import (  # noqa: E402
    GOAL_ID,
    SCHEMA_VERSION,
    TASK_ID,
    FederalRegisterFulltextError,
    InventoryRewriteError,
    LiveFulltextDisabledError,
    build_compact_coverage_recipe,
    build_fixture_coverage_report,
    check_coverage_report,
    default_report_path,
    expand_coverage_payload,
    load_json_object,
    render_check_summary,
    write_coverage_report,
)
from ipfs_datasets_py.processors.legal_data.federal_register_source_policy import (  # noqa: E402
    DEFAULT_OBSERVATION_CUTOFF,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Acquire official Federal Register body text and classify every "
            f"missing-body disposition ({TASK_ID} / {GOAL_ID}, schema "
            f"{SCHEMA_VERSION}). Default fixture mode never contacts the network "
            "and never rewrites the official inventory."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use the sealed offline fixture inventory and bodies (required for CI).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the frozen coverage report (or the fixture coverage "
            "when the report is missing under --fixture-only) against sealed "
            "acceptance."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the fixture coverage recipe to --report.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Path to the frozen coverage report "
            f"(default: {default_report_path(REPOSITORY_ROOT)})"
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
            "Enable live FederalRegister.gov / GovInfo full-text acquisition. "
            "Never required for CI; incompatible with --fixture-only."
        ),
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the coverage report JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_report_path(REPOSITORY_ROOT)
    )

    try:
        if args.live and args.fixture_only:
            raise FederalRegisterFulltextError(
                "--live and --fixture-only are mutually exclusive"
            )

        if (args.check or args.write) and not args.fixture_only and not args.live:
            raise FederalRegisterFulltextError(
                "pass --fixture-only for the offline CI gate, or --live for "
                "network full-text acquisition"
            )

        if report_path.name == "federal_inventory.json":
            raise InventoryRewriteError(
                "refusing to write or check full-text coverage as the official "
                "inventory path"
            )

        if args.fixture_only:
            fixture_report = build_fixture_coverage_report(
                observation_cutoff=args.observation_cutoff,
            )
            recipe = build_compact_coverage_recipe(
                observation_cutoff=args.observation_cutoff,
            )

            raw_disk: Mapping[str, Any] | None = None
            if report_path.is_file():
                raw_disk = load_json_object(report_path)

            if args.write:
                write_coverage_report(recipe, report_path, replace=True)
                print(f"wrote coverage recipe: {report_path}", file=sys.stderr)
                raw_disk = recipe

            if args.check:
                fixture_result = check_coverage_report(fixture_report)
                if raw_disk is not None and raw_disk.get("mode") == "live":
                    print(
                        "live_structure_valid=True live_authority_replayed=False "
                        "authorizing=False "
                        f"digest={str(raw_disk.get('coverage_digest') or '')[:12]}"
                    )
                    report: Mapping[str, Any] = raw_disk
                    result = fixture_result
                elif raw_disk is not None:
                    result = check_coverage_report(raw_disk)
                    expanded = expand_coverage_payload(raw_disk)
                    disk_acceptance = dict(expanded.get("acceptance") or {})
                    fixture_acceptance = dict(fixture_report.get("acceptance") or {})
                    stable_keys = (
                        "every_inventory_document_classified",
                        "failed_final",
                        "failed_final_zero",
                        "no_placeholder_admitted",
                        "inventory_unmodified",
                        "secrets_absent",
                        "classified",
                        "full_text_admitted",
                        "metadata_only",
                        "excluded",
                        "quarantined",
                        "observation_cutoff",
                        "mode",
                        "previous_public_pin",
                        "inventory_task_id",
                        "all_expected_outputs_accounted",
                    )
                    disk_stable = {k: disk_acceptance.get(k) for k in stable_keys}
                    fixture_stable = {
                        k: fixture_acceptance.get(k) for k in stable_keys
                    }
                    if disk_stable != fixture_stable:
                        raise FederalRegisterFulltextError(
                            "on-disk report acceptance diverges from sealed fixture: "
                            f"disk={disk_stable} fixture={fixture_stable}"
                        )
                    report = expanded
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

            check_coverage_report(fixture_report)
            print(
                render_check_summary(
                    {
                        "ok": True,
                        "acceptance": fixture_report["acceptance"],
                        "frontier_closed": True,
                        "coverage_digest": fixture_report.get("coverage_digest"),
                        "classified": fixture_report["acceptance"]["classified"],
                    }
                )
            )
            print(
                "hint: pass --fixture-only --check to validate the frozen report",
                file=sys.stderr,
            )
            return 0

        if args.live:
            raise LiveFulltextDisabledError(
                "live Federal Register full-text crawling is opt-in and is not "
                "required for the LCR-053 fixture-only CI gate"
            )

        print(
            "error: pass --fixture-only (CI) or --live (network)",
            file=sys.stderr,
        )
        return 2
    except FederalRegisterFulltextError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
