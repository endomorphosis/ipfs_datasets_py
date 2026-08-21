#!/usr/bin/env python3
"""Hermetic evaluation of state-law term-range field-weighted BM25 (LCR-027).

Validates **row conservation**, **exact scoring** against the shared
reference BM25 formula, lexicographic term-range routes, 4,096 physical
bounds, and sample/citation queries that span all census regions and DC.

Validation gate (offline, network-free)::

    python scripts/ops/legal_data/evaluate_state_laws_bm25.py --fixture-only --check

Frozen report path: ``docs/reports/legal_corpora_reindex/bm25_evaluation.json``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.state_laws_bm25 import (  # noqa: E402
    TASK_ID,
    Bm25EvaluationError,
    Bm25ReceiptError,
    build_bm25_evaluation_report,
    check_evaluation_report,
    default_bm25_report_path,
    load_bm25_evaluation_report,
    write_bm25_evaluation_report,
)

PRODUCER: Final = "evaluate_state_laws_bm25.py"


def render_check_summary(result: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"ok={result.get('ok')}",
            f"task_id={result.get('task_id', TASK_ID)}",
            f"document_count={result.get('document_count')}",
            f"query_count={result.get('query_count')}",
            f"regions_covered={result.get('regions_covered')}",
            f"max_score_delta={result.get('max_score_delta')}",
        ]
    )


def check_report_matches_fixture(
    on_disk: Mapping[str, Any],
    fixture_report: Mapping[str, Any],
) -> None:
    """Ensure frozen report acceptance matches the live fixture evaluation."""

    for key in ("task_id", "schema_version", "schema", "goal_id"):
        if on_disk.get(key) != fixture_report.get(key):
            raise Bm25EvaluationError(
                f"on-disk {key} diverges from fixture: "
                f"disk={on_disk.get(key)!r} fixture={fixture_report.get(key)!r}"
            )
    disk_acc = on_disk.get("acceptance") or {}
    fix_acc = fixture_report.get("acceptance") or {}
    for key in (
        "row_conservation",
        "exact_scoring_parity_within_tolerance",
        "documents_equal_admitted_searchable_chunks",
        "posting_routes_lexicographic",
        "physical_bounds_hold",
        "sample_queries_span_all_regions_and_dc",
        "scores_match_reference_bm25",
        "hub_upload",
    ):
        if disk_acc.get(key) != fix_acc.get(key):
            raise Bm25EvaluationError(
                f"on-disk acceptance[{key!r}] diverges from fixture: "
                f"disk={disk_acc.get(key)!r} fixture={fix_acc.get(key)!r}"
            )
    disk_corpus = on_disk.get("admitted") or {}
    fix_corpus = fixture_report.get("admitted") or {}
    for key in ("document_count", "term_count", "posting_count"):
        if disk_corpus.get(key) != fix_corpus.get(key):
            raise Bm25EvaluationError(
                f"on-disk admitted[{key!r}] diverges from fixture: "
                f"disk={disk_corpus.get(key)!r} fixture={fix_corpus.get(key)!r}"
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prove state-law term-range field-weighted BM25 on sealed fixtures "
            "(LCR-027). Default fixture mode never contacts the network."
        )
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Use sealed offline fixtures (required for CI checks).",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate the frozen report (or the live fixture evaluation when "
            "the report is missing under --fixture-only) against sealed "
            "acceptance."
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Path to the frozen report (default: docs/reports/legal_corpora_reindex/bm25_evaluation.json)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the fixture evaluation report to --report.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the evaluation report JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_bm25_report_path()
    )

    try:
        if (args.check or args.write) and not args.fixture_only:
            raise Bm25EvaluationError(
                "live corpus evaluation is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline fixture"
            )

        fixture_report = build_bm25_evaluation_report()

        if args.fixture_only and (args.write or args.check):
            write_bm25_evaluation_report(report_path)
            print(f"wrote bm25 evaluation report: {report_path}", file=sys.stderr)

        if args.check:
            if report_path.is_file():
                on_disk = load_bm25_evaluation_report(report_path)
                check_evaluation_report(on_disk)
                check_report_matches_fixture(on_disk, fixture_report)
                report: Mapping[str, Any] = on_disk
            elif args.fixture_only:
                report = fixture_report
            else:
                raise Bm25EvaluationError(
                    f"evaluation report not found for --check: {report_path}"
                )
            result = check_evaluation_report(report)
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

        result = check_evaluation_report(fixture_report)
        print(render_check_summary(result))
        print(
            "hint: pass --fixture-only --check to validate the frozen report",
            file=sys.stderr,
        )
        return 0
    except (Bm25EvaluationError, Bm25ReceiptError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
