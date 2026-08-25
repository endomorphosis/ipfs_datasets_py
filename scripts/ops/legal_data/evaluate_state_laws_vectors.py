#!/usr/bin/env python3
"""Hermetic evaluation of state-law centroid-routed vectors (LCR-029).

Validates **row conservation**, **centroid/two-shard bounds**, cosine-sorted
physical shards, direct CID locators, determinism, exhaustive recall, and
probe selection against sealed LCR-028 hashed-projection embeddings.

Validation gate (offline, network-free)::

    python scripts/ops/legal_data/evaluate_state_laws_vectors.py --fixture-only --check

Frozen report path: ``docs/reports/legal_corpora_reindex/vector_evaluation.json``.
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

from ipfs_datasets_py.processors.legal_data.state_laws_vectors import (  # noqa: E402
    TASK_ID,
    VectorEvaluationError,
    VectorReceiptError,
    VectorReleaseAuthorizationError,
    StateLawsVectorError,
    build_vector_evaluation_report,
    check_evaluation_report,
    check_report_matches_fixture,
    default_vector_evaluation_report_path,
    load_vector_evaluation_report,
    write_vector_evaluation_report,
)

PRODUCER: Final = "evaluate_state_laws_vectors.py"


def render_check_summary(result: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"ok={result.get('ok')}",
            f"task_id={result.get('task_id', TASK_ID)}",
            f"vector_count={result.get('vector_count')}",
            f"cluster_count={result.get('cluster_count')}",
            f"shard_count={result.get('shard_count')}",
            f"default_probe_centroids={result.get('default_probe_centroids')}",
            f"recall_gates_pass={result.get('recall_gates_pass')}",
            f"hub_upload={result.get('hub_upload')}",
            f"authorizing_for_publication={result.get('authorizing_for_publication')}",
            f"secrets_absent={result.get('secrets_absent')}",
        ]
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prove state-law deterministic centroid-routed vectors on sealed "
            "fixtures (LCR-029). Default fixture mode never contacts the network."
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
            "docs/reports/legal_corpora_reindex/vector_evaluation.json)"
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
        else default_vector_evaluation_report_path()
    )

    try:
        if (args.check or args.write) and not args.fixture_only:
            raise VectorEvaluationError(
                "live corpus evaluation is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline fixture"
            )

        fixture_report = build_vector_evaluation_report()

        if args.fixture_only and (args.write or args.check):
            write_vector_evaluation_report(report_path)
            print(
                f"wrote vector evaluation report: {report_path}",
                file=sys.stderr,
            )

        if args.check:
            if report_path.is_file():
                on_disk = load_vector_evaluation_report(report_path)
                check_evaluation_report(on_disk)
                check_report_matches_fixture(on_disk, fixture_report)
                report: Mapping[str, Any] = on_disk
            elif args.fixture_only:
                report = fixture_report
            else:
                raise VectorEvaluationError(
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
        VectorEvaluationError,
        VectorReceiptError,
        VectorReleaseAuthorizationError,
        StateLawsVectorError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
