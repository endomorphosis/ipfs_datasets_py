#!/usr/bin/env python3
"""Coordinate prior state-law evidence and lease only missing live scrapes.

OUL-006 treats receipts from the separate state-laws supervisor as untrusted
inputs. They are reused only after byte and frontier verification. Live
jurisdiction leases prevent duplicate scraping. Missing or invalid
jurisdictions are scheduled exactly once. Synthetic two-row reports are
never trusted.

Validation gate (no network, no mutation)::

    python scripts/ops/legal_data/coordinate_open_us_law_scrapes.py --no-mutate --check

Later cohort certifiers consume the declared Open US Law cohort report::

    python scripts/ops/legal_data/coordinate_open_us_law_scrapes.py \\
        --cohort C --report docs/reports/open_us_law_reindex/cohort_C.json \\
        --require-live --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    GOAL_ID,
    PRODUCER,
    PROGRAM_ID,
    TASK_ID,
    AcquisitionCoordinationError,
    DuplicateLeaseError,
    DuplicateScheduleError,
    LeaseReportError,
    LiveEvidenceRequiredError,
    build_acquisition_leases_payload,
    check_committed_leases,
    cohort_codes,
    default_cohort_report_path,
    default_lease_report_path,
    encode_acquisition_leases,
    validate_acquisition_leases,
    write_acquisition_leases,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    FixtureCompletionForbiddenError,
    LiveEvidenceError,
    RawBytesUncheckedError,
)

CODE_VERSION = "1"


class CoordinateError(RuntimeError):
    """Fail-closed CLI coordination failure."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Coordinate prior state-law evidence and lease only missing live "
            "Open US Law scrapes."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the committed acquisition_leases.json report.",
    )
    parser.add_argument(
        "--no-mutate",
        action="store_true",
        help="Forbid writing the lease report or any other artifact.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Regenerate and atomically write the sealed lease report.",
    )
    parser.add_argument(
        "--cohort",
        default="",
        help="Optional cohort letter (A-M) used by later scrape certifiers.",
    )
    parser.add_argument(
        "--require-live",
        action="store_true",
        help=(
            "Require verified live receipts (byte + frontier) for the selected "
            "cohort or the full exact-51 set."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the coordination report as JSON.",
    )
    parser.add_argument(
        "--report",
        default="",
        help=(
            "Declared cohort evidence path for --cohort checks, or the sealed "
            "lease report for --write. Cohort-scoped --require-live consumes "
            "docs/reports/open_us_law_reindex/cohort_<letter>.json, not the "
            "older legal_corpora_reindex receipt directory."
        ),
    )
    return parser


def _print_json(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _failed_payload(exc: BaseException) -> dict[str, Any]:
    return {
        "authorizing_for_publication": False,
        "error": str(exc),
        "goal_id": GOAL_ID,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "status": "failed",
        "task_id": TASK_ID,
    }


def _report_path(raw: str) -> Path:
    if raw.strip():
        return Path(raw).expanduser().resolve()
    return default_lease_report_path(REPOSITORY_ROOT)


def run_check(
    *,
    require_live: bool,
    cohort: Optional[str],
    report_path: Optional[Path] = None,
) -> dict[str, Any]:
    try:
        if cohort:
            cohort_codes(cohort)
        declared = report_path
        if declared is None and cohort:
            candidate = default_cohort_report_path(cohort, REPOSITORY_ROOT)
            if candidate.is_file() or require_live:
                declared = candidate
        return check_committed_leases(
            repo_root=REPOSITORY_ROOT,
            require_live=require_live,
            cohort=cohort,
            report_path=declared,
        )
    except (
        AcquisitionCoordinationError,
        DuplicateLeaseError,
        DuplicateScheduleError,
        FixtureCompletionForbiddenError,
        LeaseReportError,
        LiveEvidenceError,
        LiveEvidenceRequiredError,
        RawBytesUncheckedError,
    ) as exc:
        raise CoordinateError(str(exc)) from exc


def run_write(path: Path) -> dict[str, Any]:
    try:
        payload = build_acquisition_leases_payload(repo_root=REPOSITORY_ROOT)
        validate_acquisition_leases(payload)
        write_acquisition_leases(path, payload, repo_root=REPOSITORY_ROOT)
    except (
        AcquisitionCoordinationError,
        DuplicateLeaseError,
        DuplicateScheduleError,
        LeaseReportError,
    ) as exc:
        raise CoordinateError(str(exc)) from exc
    return {
        "authorizing_for_publication": False,
        "bytes_written": len(encode_acquisition_leases(payload)),
        "goal_id": GOAL_ID,
        "jurisdiction_count": payload["jurisdiction_count"],
        "path": path.as_posix(),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "report_digest_sha256": payload["report_digest_sha256"],
        "status": "written",
        "task_id": TASK_ID,
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.write and args.no_mutate:
        sys.stderr.write(
            "coordinate_open_us_law_scrapes: FAILED: --write is incompatible "
            "with --no-mutate\n"
        )
        return 2
    if not args.check and not args.write:
        sys.stderr.write(
            "coordinate_open_us_law_scrapes: FAILED: --check or --write is required\n"
        )
        return 2

    cohort = str(args.cohort or "").strip().upper() or None
    if args.write:
        if args.require_live:
            sys.stderr.write(
                "coordinate_open_us_law_scrapes: FAILED: --require-live applies "
                "to --check only\n"
            )
            return 2
        try:
            report = run_write(_report_path(args.report))
        except CoordinateError as exc:
            if args.json:
                _print_json(_failed_payload(exc))
            else:
                sys.stderr.write(f"coordinate_open_us_law_scrapes: FAILED: {exc}\n")
            return 1
        if args.json:
            _print_json(report)
        else:
            sys.stdout.write(
                "coordinate_open_us_law_scrapes: WROTE "
                f"(jurisdictions={report['jurisdiction_count']} "
                f"digest={report['report_digest_sha256']})\n"
            )
        return 0

    try:
        explicit_report = Path(args.report).expanduser().resolve() if str(args.report or "").strip() else None
        report = run_check(
            require_live=bool(args.require_live),
            cohort=cohort,
            report_path=explicit_report,
        )
    except CoordinateError as exc:
        if args.json:
            _print_json(_failed_payload(exc))
        else:
            sys.stderr.write(f"coordinate_open_us_law_scrapes: FAILED: {exc}\n")
        return 1

    if args.json:
        _print_json(report)
    else:
        jurisdictions = report.get("jurisdiction_count")
        if jurisdictions is None:
            jurisdictions = len(report.get("jurisdictions") or [])
        sys.stdout.write(
            "coordinate_open_us_law_scrapes: PASSED "
            f"(jurisdictions={jurisdictions} "
            f"exact_51={report.get('exact_51', False)} "
            f"dc_counted_once={report.get('dc_counted_once', True)} "
            f"scheduled={report.get('scheduled_count', 0)} "
            f"two_row_rejected={report.get('two_row_reports_rejected', 0)})\n"
            f"  digest={report.get('report_digest_sha256') or ''}\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
