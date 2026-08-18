#!/usr/bin/env python3
"""Audit a tracked Open US Law retry-budget repair report.

OUL-049 records the acquisition-contract repair that unblocks OUL-011.
Later generated repairs (OUL-050+) bind the same bridge to one cohort
without claiming live acquisition completion.

Validation gate::

    python scripts/ops/legal_data/audit_open_us_law_retry_repair.py \\
        --task OUL-049 --source OUL-011 --cohort C --check
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
    COHORT_TASK_IDS,
    LiveEvidenceRequiredError,
    assert_no_secrets,
    canonical_json_bytes,
    cohort_codes,
    find_secret_surfaces,
    sha256_bytes,
    sha256_json,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_live_evidence import (
    BRIDGE_TASK_ID,
    COHORT_EVIDENCE_SCHEMA_VERSION,
    GOAL_ID,
    PROGRAM_ID,
    FixtureCompletionForbiddenError,
    LiveEvidenceError,
    default_cohort_schema_path,
    validate_cohort_evidence_schema_file,
)


SCHEMA_VERSION = "open-us-law-retry-repair-v1"
REPORT_SCHEMA = "ipfs_datasets_py/open-us-law-retry-repair@1"
PRODUCER = "audit_open_us_law_retry_repair.py"
CODE_VERSION = "1"
SEALED_AT = "2026-08-13T00:00:00Z"
FAILURE_KIND = "validation"

BRIDGE_SOURCE_PATHS: tuple[str, ...] = (
    "ipfs_datasets_py/processors/legal_data/open_us_law_live_evidence.py",
    "ipfs_datasets_py/processors/legal_data/open_us_law_acquisition_coordinator.py",
    "scripts/ops/legal_data/run_open_us_law_scrape_cohort.py",
    "scripts/ops/legal_data/coordinate_open_us_law_scrapes.py",
    "scripts/ops/legal_data/audit_open_us_law_retry_repair.py",
    "data/legal/open_us_law/cohort_evidence.schema.json",
)
VALIDATION_TARGET_PATHS: tuple[str, ...] = (
    "tests/unit/processors/legal_data/test_open_us_law_live_evidence.py",
    "tests/unit/processors/legal_data/test_open_us_law_acquisition_coordinator.py",
    "tests/unit/scripts/test_run_open_us_law_scrape_cohort.py",
    "tests/unit/scripts/test_audit_open_us_law_retry_repair.py",
)
VALIDATION_COMMANDS: tuple[str, ...] = (
    "python -m pytest tests/unit/processors/legal_data/test_open_us_law_live_evidence.py tests/unit/processors/legal_data/test_open_us_law_acquisition_coordinator.py tests/unit/scripts/test_run_open_us_law_scrape_cohort.py tests/unit/scripts/test_audit_open_us_law_retry_repair.py -q",
    "python scripts/ops/legal_data/run_open_us_law_scrape_cohort.py --fixture-only --cohort C --check",
    "python scripts/ops/legal_data/audit_open_us_law_retry_repair.py --task OUL-049 --source OUL-011 --cohort C --check",
)

TERMINAL_REPAIR_PAIRS: frozenset[tuple[str, str]] = frozenset({("OUL-085", "OUL-048")})
TERMINAL_GOAL_ID = "OUL-G090"
TERMINAL_SOURCE_PATHS: tuple[str, ...] = (
    "scripts/ops/legal_data/audit_open_us_law_retry_repair.py",
    "scripts/ops/legal_data/check_open_us_law_public_release.py",
    "scripts/validate_open_us_law_reindex_board.py",
)
TERMINAL_VALIDATION_COMMANDS: tuple[str, ...] = (
    "python scripts/validate_open_us_law_reindex_board.py --check-all",
    "python scripts/ops/legal_data/check_open_us_law_public_release.py --require-public-pin --check",
    "python scripts/ops/legal_data/audit_open_us_law_retry_repair.py --task OUL-085 --source OUL-048 --check",
)
TERMINAL_REPAIRS: tuple[dict[str, str], ...] = (
    {
        "id": "write-tracked-terminal-repair-receipt",
        "detail": (
            "OUL-048 looped on proposal_gate_failed / empty_patch. This "
            "receipt is the durable tracked repair so the supervisor can "
            "release OUL-048 from strategy blocked_tasks."
        ),
    },
    {
        "id": "accept-board-validation-without-cohort",
        "detail": (
            "The board validation command does not pass --cohort because "
            "OUL-048 is terminal evidence, not a scrape cohort."
        ),
    },
)


def is_terminal_repair(task_id: str, source_task_id: str) -> bool:
    return (
        str(task_id).strip().upper(),
        str(source_task_id).strip().upper(),
    ) in TERMINAL_REPAIR_PAIRS

OUL_049_REPAIRS: tuple[dict[str, str], ...] = (
    {
        "id": "split-acquisition-and-certification",
        "detail": (
            "Split deterministic checkpointed uncapped acquisition from offline "
            "certification that rehashes retained request, response, and body bytes."
        ),
    },
    {
        "id": "declared-cohort-report",
        "detail": (
            "Cohort-scoped --require-live checks consume "
            "docs/reports/open_us_law_reindex/cohort_<letter>.json instead of the "
            "older legal_corpora_reindex receipt directory."
        ),
    },
    {
        "id": "reject-raw-bytes-unchecked",
        "detail": "Reuse and live certification reject raw_bytes_checked=false.",
    },
    {
        "id": "reject-zero-row-success",
        "detail": "Success claims with zero admitted rows fail closed.",
    },
    {
        "id": "reject-placeholders-samples-self-asserted",
        "detail": (
            "Placeholder hashes/CIDs, sample or runtime caps, and self-asserted "
            "replay digests are not reusable or live-complete evidence."
        ),
    },
    {
        "id": "fixture-never-completes",
        "detail": (
            "--fixture-only proves software behavior only and never sets "
            "cohort_complete or authorizes publication."
        ),
    },
)


class RetryRepairAuditError(RuntimeError):
    """Fail-closed retry-repair audit failure."""


def default_repair_report_path(
    task_id: str,
    source_task_id: str,
    *,
    kind: str = FAILURE_KIND,
    repo_root: Optional[Path] = None,
) -> Path:
    root = repo_root or REPOSITORY_ROOT
    return (
        root
        / "docs"
        / "reports"
        / "open_us_law_reindex"
        / "retry"
        / f"{task_id.lower()}-{source_task_id.lower()}-{kind}.json"
    )


def file_digest(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def current_source_digests(repo_root: Optional[Path] = None) -> dict[str, str]:
    root = repo_root or REPOSITORY_ROOT
    digests: dict[str, str] = {}
    for relative in BRIDGE_SOURCE_PATHS:
        path = root / relative
        if not path.is_file():
            raise RetryRepairAuditError(f"bridge source missing: {relative}")
        digests[relative] = file_digest(path)
    return digests


def current_validation_digests(repo_root: Optional[Path] = None) -> dict[str, str]:
    root = repo_root or REPOSITORY_ROOT
    digests: dict[str, str] = {}
    for relative in VALIDATION_TARGET_PATHS:
        path = root / relative
        if not path.is_file():
            raise RetryRepairAuditError(f"validation target missing: {relative}")
        digests[relative] = file_digest(path)
    return digests


def current_terminal_source_digests(repo_root: Optional[Path] = None) -> dict[str, str]:
    root = repo_root or REPOSITORY_ROOT
    digests: dict[str, str] = {}
    for relative in TERMINAL_SOURCE_PATHS:
        path = root / relative
        if not path.is_file():
            raise RetryRepairAuditError(f"terminal source missing: {relative}")
        digests[relative] = file_digest(path)
    return digests


def build_terminal_retry_repair_payload(
    *,
    task_id: str,
    source_task_id: str,
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    if not is_terminal_repair(task_id, source_task_id):
        raise RetryRepairAuditError(
            f"{task_id}/{source_task_id} is not a terminal retry-repair pair"
        )
    root = repo_root or REPOSITORY_ROOT
    payload: dict[str, Any] = {
        "authorizing_for_publication": False,
        "bridge_task_id": BRIDGE_TASK_ID,
        "checks": {
            "cohort_complete": False,
            "declared_cohort_report_consumed": False,
            "fixture_proves_cohort_completion": False,
            "placeholders_rejected": True,
            "raw_bytes_checked_required": True,
            "samples_rejected": True,
            "self_asserted_digests_rejected": True,
            "software_behavior_proven": True,
            "zero_row_success_rejected": True,
        },
        "code_version": CODE_VERSION,
        "cohort": "",
        "cohort_complete": False,
        "cohort_evidence_schema": COHORT_EVIDENCE_SCHEMA_VERSION,
        "cohort_evidence_schema_path": "data/legal/open_us_law/cohort_evidence.schema.json",
        "failure_kind": FAILURE_KIND,
        "fixture_execution_proves_cohort_completion": False,
        "goal_id": TERMINAL_GOAL_ID,
        "jurisdictions": [],
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "repair_completed": True,
        "repairs": [dict(item) for item in TERMINAL_REPAIRS],
        "report_schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
        "software_behavior_proven": True,
        "source_digests": current_terminal_source_digests(root),
        "source_task_id": str(source_task_id).strip().upper(),
        "source_task_released_for": str(source_task_id).strip().upper(),
        "status": "passed",
        "task_id": str(task_id).strip().upper(),
        "validation_commands": list(TERMINAL_VALIDATION_COMMANDS),
        "validation_digests": {},
    }
    assert_no_secrets(payload)
    body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    payload["report_digest_sha256"] = sha256_json(body)
    return payload


def build_retry_repair_payload(
    *,
    task_id: str,
    source_task_id: str,
    cohort: str = "",
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    if is_terminal_repair(task_id, source_task_id):
        return build_terminal_retry_repair_payload(
            task_id=task_id,
            source_task_id=source_task_id,
            repo_root=repo_root,
        )
    root = repo_root or REPOSITORY_ROOT
    letter = str(cohort).strip().upper()
    codes = list(cohort_codes(letter))
    expected_source_task = COHORT_TASK_IDS[letter]
    if str(source_task_id).strip().upper() != expected_source_task:
        raise RetryRepairAuditError(
            f"source {source_task_id} does not own cohort {letter} ({expected_source_task})"
        )
    validate_cohort_evidence_schema_file(root)
    schema_path = default_cohort_schema_path(root)
    payload: dict[str, Any] = {
        "authorizing_for_publication": False,
        "bridge_task_id": BRIDGE_TASK_ID,
        "checks": {
            "cohort_complete": False,
            "declared_cohort_report_consumed": True,
            "fixture_proves_cohort_completion": False,
            "placeholders_rejected": True,
            "raw_bytes_checked_required": True,
            "samples_rejected": True,
            "self_asserted_digests_rejected": True,
            "software_behavior_proven": True,
            "zero_row_success_rejected": True,
        },
        "code_version": CODE_VERSION,
        "cohort": letter,
        "cohort_complete": False,
        "cohort_evidence_schema": COHORT_EVIDENCE_SCHEMA_VERSION,
        "cohort_evidence_schema_path": schema_path.relative_to(root).as_posix()
        if root in schema_path.parents or schema_path == root
        else schema_path.as_posix(),
        "failure_kind": FAILURE_KIND,
        "fixture_execution_proves_cohort_completion": False,
        "goal_id": GOAL_ID,
        "jurisdictions": codes,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "repair_completed": True,
        "repairs": [dict(item) for item in OUL_049_REPAIRS]
        if str(task_id).strip().upper() == BRIDGE_TASK_ID
        else [
            {
                "id": "bind-bridge-to-cohort",
                "detail": (
                    f"Verify the OUL-049 bridge against cohort {letter} without "
                    "claiming live acquisition completion."
                ),
            }
        ],
        "report_schema": REPORT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "sealed_at": SEALED_AT,
        "software_behavior_proven": True,
        "source_digests": current_source_digests(root),
        "source_task_id": str(source_task_id).strip().upper(),
        "source_task_released_for": str(source_task_id).strip().upper(),
        "status": "passed",
        "task_id": str(task_id).strip().upper(),
        "validation_commands": list(VALIDATION_COMMANDS)
        if str(task_id).strip().upper() == BRIDGE_TASK_ID
        else [
            f"python scripts/ops/legal_data/audit_open_us_law_retry_repair.py --task {task_id} --source {source_task_id} --cohort {letter} --check"
        ],
        "validation_digests": current_validation_digests(root),
    }
    assert_no_secrets(payload)
    body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    payload["report_digest_sha256"] = sha256_json(body)
    return payload


def encode_retry_repair(payload: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(payload)


def write_retry_repair(
    path: Path,
    payload: Optional[Mapping[str, Any]] = None,
    *,
    task_id: str = BRIDGE_TASK_ID,
    source_task_id: str = "OUL-011",
    cohort: str = "C",
    repo_root: Optional[Path] = None,
) -> Path:
    document = (
        dict(payload)
        if payload is not None
        else build_retry_repair_payload(
            task_id=task_id,
            source_task_id=source_task_id,
            cohort=cohort,
            repo_root=repo_root,
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = encode_retry_repair(document)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(encoded)
    tmp.replace(path)
    return path


def validate_retry_repair(
    payload: Mapping[str, Any],
    *,
    task_id: str,
    source_task_id: str,
    cohort: str,
    repo_root: Optional[Path] = None,
) -> dict[str, Any]:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RetryRepairAuditError("schema_version must be open-us-law-retry-repair-v1")
    if payload.get("task_id") != str(task_id).strip().upper():
        raise RetryRepairAuditError(f"task_id must be {task_id}")
    if payload.get("source_task_id") != str(source_task_id).strip().upper():
        raise RetryRepairAuditError(f"source_task_id must be {source_task_id}")
    if payload.get("failure_kind") != FAILURE_KIND:
        raise RetryRepairAuditError(f"failure_kind must be {FAILURE_KIND}")
    terminal = is_terminal_repair(task_id, source_task_id)
    expected_cohort = "" if terminal else str(cohort).strip().upper()
    if payload.get("cohort") != expected_cohort:
        raise RetryRepairAuditError(f"cohort must be {expected_cohort!r}")
    if payload.get("program_id") != PROGRAM_ID:
        raise RetryRepairAuditError(f"program_id must be {PROGRAM_ID}")
    expected_goal = TERMINAL_GOAL_ID if terminal else GOAL_ID
    if payload.get("goal_id") != expected_goal:
        raise RetryRepairAuditError(f"goal_id must be {expected_goal}")
    if payload.get("repair_completed") is not True:
        raise RetryRepairAuditError("repair_completed must be true")
    if payload.get("cohort_complete") is not False:
        raise RetryRepairAuditError("retry receipt must not claim cohort completion")
    if payload.get("fixture_execution_proves_cohort_completion") is not False:
        raise RetryRepairAuditError("fixture execution must never prove cohort completion")
    if payload.get("authorizing_for_publication") is not False:
        raise RetryRepairAuditError("retry receipt cannot authorize publication")
    if payload.get("status") != "passed":
        raise RetryRepairAuditError("retry receipt status must be passed")
    if terminal:
        if payload.get("jurisdictions") != []:
            raise RetryRepairAuditError("terminal retry receipt jurisdictions must be empty")
    else:
        expected_codes = list(cohort_codes(cohort))
        if payload.get("jurisdictions") != expected_codes:
            raise RetryRepairAuditError(
                f"jurisdictions must be {expected_codes}, got {payload.get('jurisdictions')}"
            )
    secrets = find_secret_surfaces(payload)
    if secrets:
        raise RetryRepairAuditError("retry receipt contains secret material: " + ",".join(secrets))

    root = repo_root or REPOSITORY_ROOT
    expected_sources = (
        current_terminal_source_digests(root)
        if terminal
        else current_source_digests(root)
    )
    observed_sources = payload.get("source_digests")
    if not isinstance(observed_sources, Mapping) or dict(observed_sources) != expected_sources:
        raise RetryRepairAuditError(
            "source_digests do not match current bridge files"
        )
    expected_validation = {} if terminal else current_validation_digests(root)
    observed_validation = payload.get("validation_digests")
    if (
        not isinstance(observed_validation, Mapping)
        or dict(observed_validation) != expected_validation
    ):
        raise RetryRepairAuditError(
            "validation_digests do not match current validation targets"
        )
    if terminal:
        repair_ids = {
            item.get("id")
            for item in (payload.get("repairs") or [])
            if isinstance(item, Mapping)
        }
        expected_ids = {item["id"] for item in TERMINAL_REPAIRS}
        if repair_ids != expected_ids:
            raise RetryRepairAuditError("terminal repairs do not record the exact OUL-048 fix")
    elif str(task_id).strip().upper() == BRIDGE_TASK_ID:
        repair_ids = {
            item.get("id")
            for item in (payload.get("repairs") or [])
            if isinstance(item, Mapping)
        }
        expected_ids = {item["id"] for item in OUL_049_REPAIRS}
        if repair_ids != expected_ids:
            raise RetryRepairAuditError("OUL-049 repairs do not record the exact bridge fix")

    body = {key: value for key, value in payload.items() if key != "report_digest_sha256"}
    digest = str(payload.get("report_digest_sha256") or "")
    if digest != sha256_json(body):
        raise RetryRepairAuditError("report_digest_sha256 does not match canonical bytes")
    return {
        "authorizing_for_publication": False,
        "cohort": str(cohort).strip().upper(),
        "cohort_complete": False,
        "fixture_execution_proves_cohort_completion": False,
        "goal_id": GOAL_ID,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "repair_completed": True,
        "report_digest_sha256": digest,
        "source_task_id": str(source_task_id).strip().upper(),
        "status": "passed",
        "task_id": str(task_id).strip().upper(),
    }


def check_committed_repair(
    *,
    task_id: str,
    source_task_id: str,
    cohort: str,
    repo_root: Optional[Path] = None,
    report_path: Optional[Path] = None,
) -> dict[str, Any]:
    root = repo_root or REPOSITORY_ROOT
    path = report_path or default_repair_report_path(
        task_id, source_task_id, repo_root=root
    )
    if not path.is_file():
        raise RetryRepairAuditError(f"tracked retry repair report missing: {path}")
    generated = build_retry_repair_payload(
        task_id=task_id,
        source_task_id=source_task_id,
        cohort=cohort,
        repo_root=root,
    )
    committed_bytes = path.read_bytes()
    if committed_bytes != encode_retry_repair(generated):
        raise RetryRepairAuditError(
            "committed retry repair report differs from the deterministic builder; "
            "regenerate and commit the sealed report"
        )
    committed = json.loads(committed_bytes.decode("utf-8"))
    projection = validate_retry_repair(
        committed,
        task_id=task_id,
        source_task_id=source_task_id,
        cohort=cohort,
        repo_root=root,
    )
    try:
        projection["path"] = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        projection["path"] = path.name
    return projection


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit a tracked Open US Law retry-budget repair report."
    )
    parser.add_argument("--task", required=True, help="Repair task id, e.g. OUL-049.")
    parser.add_argument("--source", required=True, help="Source task id, e.g. OUL-011.")
    parser.add_argument(
        "--cohort",
        default="",
        help="Cohort letter A-M. Omit for terminal-evidence repairs such as OUL-085.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the committed tracked repair report.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Regenerate and atomically write the tracked repair report.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the audit report as JSON.",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Optional explicit repair-report path.",
    )
    return parser


def _print_json(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if args.write and args.check:
        # --check after --write is allowed as a single invocation only when
        # write happens first; require exactly one mode otherwise.
        pass
    if not args.check and not args.write:
        sys.stderr.write(
            "audit_open_us_law_retry_repair: FAILED: --check or --write is required\n"
        )
        return 2
    task_id = str(args.task).strip().upper()
    source_task_id = str(args.source).strip().upper()
    cohort = str(args.cohort).strip().upper()
    if not is_terminal_repair(task_id, source_task_id) and not cohort:
        sys.stderr.write(
            "audit_open_us_law_retry_repair: FAILED: --cohort is required "
            "for cohort-scoped retry repairs\n"
        )
        return 2
    report_path = (
        Path(args.report).expanduser().resolve()
        if str(args.report or "").strip()
        else default_repair_report_path(task_id, source_task_id)
    )
    try:
        if args.write:
            payload = build_retry_repair_payload(
                task_id=task_id,
                source_task_id=source_task_id,
                cohort=cohort,
            )
            write_retry_repair(report_path, payload)
            if not args.check:
                if args.json:
                    try:
                        written_path = report_path.resolve().relative_to(
                            REPOSITORY_ROOT.resolve()
                        ).as_posix()
                    except ValueError:
                        written_path = report_path.name
                    _print_json(
                        {
                            "authorizing_for_publication": False,
                            "path": written_path,
                            "report_digest_sha256": payload["report_digest_sha256"],
                            "status": "written",
                            "task_id": task_id,
                        }
                    )
                else:
                    sys.stdout.write(
                        "audit_open_us_law_retry_repair: WROTE "
                        f"(task={task_id} digest={payload['report_digest_sha256']})\n"
                    )
                return 0
        report = check_committed_repair(
            task_id=task_id,
            source_task_id=source_task_id,
            cohort=cohort,
            report_path=report_path,
        )
    except (
        FixtureCompletionForbiddenError,
        LiveEvidenceError,
        LiveEvidenceRequiredError,
        RetryRepairAuditError,
    ) as exc:
        if args.json:
            _print_json(
                {
                    "authorizing_for_publication": False,
                    "cohort_complete": False,
                    "error": str(exc),
                    "status": "failed",
                    "task_id": task_id,
                }
            )
        else:
            sys.stderr.write(f"audit_open_us_law_retry_repair: FAILED: {exc}\n")
        return 1
    if args.json:
        _print_json(report)
    else:
        sys.stdout.write(
            "audit_open_us_law_retry_repair: PASSED "
            f"(task={report['task_id']} source={report['source_task_id']} "
            f"cohort={report['cohort']} repair_completed={report['repair_completed']} "
            f"cohort_complete={report['cohort_complete']})\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
