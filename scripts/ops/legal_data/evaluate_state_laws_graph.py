#!/usr/bin/env python3
"""Hermetic evaluation of the state-law legal and provenance graph (LCR-030).

Validates **node/edge uniqueness**, **referential integrity**, exact-51
jurisdiction coverage, unresolved-citation accounting, and the invariant
that similarity/BM25/embedding neighbors are never legal authority.

Validation gate (offline, network-free)::

    python scripts/ops/legal_data/evaluate_state_laws_graph.py --fixture-only --check

Frozen report path: ``docs/reports/legal_corpora_reindex/graph_evaluation.json``.
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

from ipfs_datasets_py.processors.legal_data.state_laws_graph import (  # noqa: E402
    TASK_ID,
    GraphEvaluationError,
    GraphReceiptError,
    GraphReleaseAuthorizationError,
    StateLawsGraphError,
    build_graph_evaluation_report,
    check_evaluation_report,
    default_graph_evaluation_report_path,
    load_graph_evaluation_report,
    write_graph_evaluation_report,
)

PRODUCER: Final = "evaluate_state_laws_graph.py"


def render_check_summary(result: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"ok={result.get('ok')}",
            f"task_id={result.get('task_id', TASK_ID)}",
            f"node_count={result.get('node_count')}",
            f"edge_count={result.get('edge_count')}",
            f"jurisdiction_count={result.get('jurisdiction_count')}",
            f"unresolved_count={result.get('unresolved_count')}",
            f"similarity_not_authority={result.get('similarity_not_authority')}",
        ]
    )


def check_report_matches_fixture(
    on_disk: Mapping[str, Any],
    fixture_report: Mapping[str, Any],
) -> None:
    """Ensure frozen report acceptance matches the live fixture evaluation."""

    for key in ("task_id", "schema_version", "schema", "goal_id"):
        if on_disk.get(key) != fixture_report.get(key):
            raise GraphEvaluationError(
                f"on-disk {key} diverges from fixture: "
                f"disk={on_disk.get(key)!r} fixture={fixture_report.get(key)!r}"
            )
    disk_acc = on_disk.get("acceptance") or {}
    fix_acc = fixture_report.get("acceptance") or {}
    for key in (
        "uniqueness",
        "referential_integrity",
        "51_jurisdiction_coverage",
        "unresolved_citation_accounting",
        "similarity_not_authority",
        "secrets_absent",
        "hub_upload",
        "authorizing_for_publication",
    ):
        if disk_acc.get(key) != fix_acc.get(key):
            raise GraphEvaluationError(
                f"on-disk acceptance[{key!r}] diverges from fixture: "
                f"disk={disk_acc.get(key)!r} fixture={fix_acc.get(key)!r}"
            )
    disk_demo = on_disk.get("demo") or {}
    fix_demo = fixture_report.get("demo") or {}
    for key in ("graph_cid", "node_count", "edge_count", "unresolved_count"):
        if disk_demo.get(key) != fix_demo.get(key):
            raise GraphEvaluationError(
                f"on-disk demo[{key!r}] diverges from fixture: "
                f"disk={disk_demo.get(key)!r} fixture={fix_demo.get(key)!r}"
            )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prove the state-law legal and provenance graph on sealed fixtures "
            "(LCR-030). Default fixture mode never contacts the network."
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
        help=(
            "Path to the frozen report (default: "
            "docs/reports/legal_corpora_reindex/graph_evaluation.json)"
        ),
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
        else default_graph_evaluation_report_path()
    )

    try:
        if (args.check or args.write) and not args.fixture_only:
            raise GraphEvaluationError(
                "live corpus evaluation is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline fixture"
            )

        fixture_report = build_graph_evaluation_report()

        if args.fixture_only and (args.write or args.check):
            write_graph_evaluation_report(report_path)
            print(f"wrote graph evaluation report: {report_path}", file=sys.stderr)

        if args.check:
            if report_path.is_file():
                on_disk = load_graph_evaluation_report(report_path)
                check_evaluation_report(on_disk)
                check_report_matches_fixture(on_disk, fixture_report)
                report: Mapping[str, Any] = on_disk
            elif args.fixture_only:
                report = fixture_report
            else:
                raise GraphEvaluationError(
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
    except (
        GraphEvaluationError,
        GraphReceiptError,
        GraphReleaseAuthorizationError,
        StateLawsGraphError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
