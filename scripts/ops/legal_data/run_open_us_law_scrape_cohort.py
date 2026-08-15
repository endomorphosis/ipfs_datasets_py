#!/usr/bin/env python3
"""Run or certify one Open US Law scrape cohort.

Acquisition and certification are separate. ``--fixture-only`` proves the
uncapped writer and offline certifier against isolated fixture artifacts
and never marks a cohort complete. ``--require-live`` consumes a declared
Open US Law cohort report and retained official bytes.

Validation gate (software behavior only)::

    python scripts/ops/legal_data/run_open_us_law_scrape_cohort.py \\
        --fixture-only --cohort C --check
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_acquisition_coordinator import (
    AcquisitionCoordinationError,
    LiveEvidenceRequiredError,
    cohort_codes,
    cohort_task_id,
    default_cohort_report_path,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    BRIDGE_TASK_ID,
    GOAL_ID,
    PROGRAM_ID,
    FixtureCompletionForbiddenError,
    LiveEvidenceError,
    RawBytesUncheckedError,
    SampleCapError,
    SelfAssertedDigestError,
    ZeroRowSuccessError,
    check_declared_cohort_report,
    prove_fixture_behavior,
    validate_cohort_evidence_schema_file,
    write_live_cohort_report,
)


PRODUCER = "run_open_us_law_scrape_cohort.py"
CODE_VERSION = "1"


class CohortRunError(RuntimeError):
    """Fail-closed cohort runner failure."""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run or certify one Open US Law scrape cohort."
    )
    parser.add_argument(
        "--cohort",
        required=True,
        help="Cohort letter A-M.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the software path or the declared live cohort report.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "Acquire the cohort through registered fetch_official hooks and "
            "write the declared live report. Never used with --fixture-only."
        ),
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help=(
            "Prove the uncapped acquisition and offline certification bridge "
            "on isolated fixture artifacts. Never claims cohort completion."
        ),
    )
    parser.add_argument(
        "--require-live",
        action="store_true",
        help="Require certified live retained evidence in the declared cohort report.",
    )
    parser.add_argument(
        "--no-mutate",
        action="store_true",
        help="Forbid writing a production cohort report.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the check report as JSON.",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Declared cohort evidence path. Defaults to docs/reports/open_us_law_reindex/cohort_<letter>.json.",
    )
    parser.add_argument(
        "--evidence-root",
        default="",
        help="Optional isolated evidence root for fixture software proof.",
    )
    return parser


def _print_json(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _failed_payload(exc: BaseException, cohort: str) -> dict[str, Any]:
    return {
        "authorizing_for_publication": False,
        "cohort": str(cohort).strip().upper(),
        "cohort_complete": False,
        "error": str(exc),
        "fixture_proves_cohort_completion": False,
        "goal_id": GOAL_ID,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "status": "failed",
        "task_id": BRIDGE_TASK_ID,
    }


def run_fixture_check(cohort: str, evidence_root: Optional[Path] = None) -> dict[str, Any]:
    validate_cohort_evidence_schema_file(REPOSITORY_ROOT)
    codes = list(cohort_codes(cohort))
    if evidence_root is None:
        with tempfile.TemporaryDirectory(prefix="oul-cohort-fixture-") as tmp:
            report = prove_fixture_behavior(cohort, Path(tmp), repo_root=REPOSITORY_ROOT)
    else:
        report = prove_fixture_behavior(cohort, evidence_root, repo_root=REPOSITORY_ROOT)
    if report.get("cohort_complete") is True:
        raise FixtureCompletionForbiddenError(
            "fixture execution proves software behavior only and never cohort completion"
        )
    report.update(
        {
            "authorizing_for_publication": False,
            "bridge_task_id": BRIDGE_TASK_ID,
            "code_version": CODE_VERSION,
            "cohort_complete": False,
            "fixture_execution": True,
            "fixture_only": True,
            "fixture_proves_cohort_completion": False,
            "jurisdictions": codes,
            "oul_task_id": cohort_task_id(codes[0]),
            "producer": PRODUCER,
            "software_behavior_proven": True,
            "status": "passed",
        }
    )
    return report


def run_live_check(cohort: str, report_path: Path) -> dict[str, Any]:
    validate_cohort_evidence_schema_file(REPOSITORY_ROOT)
    return check_declared_cohort_report(
        report_path,
        cohort=cohort,
        require_live=True,
        repo_root=REPOSITORY_ROOT,
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    cohort = str(args.cohort or "").strip().upper()
    if args.fixture_only and args.require_live:
        sys.stderr.write(
            "run_open_us_law_scrape_cohort: FAILED: --fixture-only is "
            "incompatible with --require-live\n"
        )
        return 2
    if args.write and args.fixture_only:
        sys.stderr.write(
            "run_open_us_law_scrape_cohort: FAILED: --write cannot use "
            "--fixture-only; fixture bytes never become live evidence\n"
        )
        return 2
    if args.write and args.no_mutate:
        sys.stderr.write(
            "run_open_us_law_scrape_cohort: FAILED: --write is incompatible "
            "with --no-mutate\n"
        )
        return 2
    if not args.check and not args.write:
        sys.stderr.write(
            "run_open_us_law_scrape_cohort: FAILED: --check or --write is required\n"
        )
        return 2
    if not args.fixture_only and not args.require_live:
        sys.stderr.write(
            "run_open_us_law_scrape_cohort: FAILED: pass --fixture-only "
            "for the software-behavior gate or --require-live for certified "
            "retained evidence\n"
        )
        return 2

    try:
        cohort_codes(cohort)
        report_path = (
            Path(args.report).expanduser().resolve()
            if str(args.report or "").strip()
            else default_cohort_report_path(cohort, REPOSITORY_ROOT)
        )
        if args.write:
            evidence_root = (
                Path(args.evidence_root).expanduser().resolve()
                if str(args.evidence_root or "").strip()
                else Path(tempfile.mkdtemp(prefix=f"oul-cohort-{cohort.lower()}-live-"))
            )
            report = write_live_cohort_report(
                report_path,
                cohort,
                evidence_root,
                repo_root=REPOSITORY_ROOT,
            )
            if args.check:
                report = run_live_check(cohort, report_path)
        elif args.fixture_only:
            evidence_root = (
                Path(args.evidence_root).expanduser().resolve()
                if str(args.evidence_root or "").strip()
                else None
            )
            report = run_fixture_check(cohort, evidence_root)
        else:
            report = run_live_check(cohort, report_path)
    except (
        AcquisitionCoordinationError,
        CohortRunError,
        FixtureCompletionForbiddenError,
        LiveEvidenceError,
        LiveEvidenceRequiredError,
        RawBytesUncheckedError,
        SampleCapError,
        SelfAssertedDigestError,
        ZeroRowSuccessError,
    ) as exc:
        if args.json:
            _print_json(_failed_payload(exc, cohort))
        else:
            sys.stderr.write(f"run_open_us_law_scrape_cohort: FAILED: {exc}\n")
        return 1

    if args.json:
        _print_json(report)
    else:
        sys.stdout.write(
            "run_open_us_law_scrape_cohort: PASSED "
            f"(cohort={report.get('cohort', cohort)} "
            f"software_behavior_proven={report.get('software_behavior_proven', False)} "
            f"cohort_complete={report.get('cohort_complete', False)} "
            f"fixture_only={bool(args.fixture_only)})\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
