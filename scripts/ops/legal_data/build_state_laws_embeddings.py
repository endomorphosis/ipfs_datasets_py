#!/usr/bin/env python3
"""Hermetic build of pinned state-law embeddings (LCR-028).

Validates **key-set equality** against admitted searchable chunks, the
sealed thenlper/gte-small pin (384-d, mean pooling, L2), and rejection of
zero / duplicate / orphan / NaN / stale-model / changed-input vectors.

Validation gate (offline, network-free)::

    python scripts/ops/legal_data/build_state_laws_embeddings.py --fixture-only --check

Frozen receipt path: ``docs/reports/legal_corpora_reindex/embedding_receipt.json``.
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

from ipfs_datasets_py.processors.legal_data.state_laws_embeddings import (  # noqa: E402
    TASK_ID,
    EmbeddingEvaluationError,
    EmbeddingReceiptError,
    EmbeddingReleaseAuthorizationError,
    build_embedding_receipt,
    check_embedding_receipt,
    check_receipt_matches_fixture,
    default_embedding_receipt_path,
    load_embedding_receipt,
    write_embedding_receipt,
)

PRODUCER: Final = "build_state_laws_embeddings.py"


def render_check_summary(result: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"ok={result.get('ok')}",
            f"task_id={result.get('task_id', TASK_ID)}",
            f"chunk_count={result.get('chunk_count')}",
            f"vector_count={result.get('vector_count')}",
            f"hub_upload={result.get('hub_upload')}",
            f"authorizing_for_publication={result.get('authorizing_for_publication')}",
            f"secrets_absent={result.get('secrets_absent')}",
        ]
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Prove state-law embeddings in one pinned legal vector space "
            "(LCR-028). Default fixture mode never contacts the network."
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
            "Validate the frozen receipt (or the live fixture evaluation when "
            "the receipt is missing under --fixture-only) against sealed "
            "acceptance."
        ),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help=(
            "Path to the frozen receipt (default: "
            "docs/reports/legal_corpora_reindex/embedding_receipt.json)"
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the fixture embedding receipt to --report.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the embedding receipt JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    report_path = (
        Path(args.report).expanduser().resolve()
        if args.report is not None
        else default_embedding_receipt_path()
    )

    try:
        if (args.check or args.write) and not args.fixture_only:
            raise EmbeddingEvaluationError(
                "live corpus embedding is not enabled in this gate; pass "
                "--fixture-only to use the sealed offline fixture"
            )

        fixture_report = build_embedding_receipt()

        if args.fixture_only and (args.write or args.check):
            write_embedding_receipt(report_path)
            print(f"wrote embedding receipt: {report_path}", file=sys.stderr)

        if args.check:
            if report_path.is_file():
                on_disk = load_embedding_receipt(report_path)
                check_embedding_receipt(on_disk)
                check_receipt_matches_fixture(on_disk, fixture_report)
                report: Mapping[str, Any] = on_disk
            elif args.fixture_only:
                report = fixture_report
            else:
                raise EmbeddingEvaluationError(
                    f"embedding receipt not found for --check: {report_path}"
                )
            result = check_embedding_receipt(report)
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

        result = check_embedding_receipt(fixture_report)
        print(render_check_summary(result))
        print(
            "hint: pass --fixture-only --check to validate the frozen receipt",
            file=sys.stderr,
        )
        return 0
    except (
        EmbeddingEvaluationError,
        EmbeddingReceiptError,
        EmbeddingReleaseAuthorizationError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
