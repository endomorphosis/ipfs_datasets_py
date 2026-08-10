#!/usr/bin/env python3
"""Audit the legal source-rights and redistribution admission contract (LCR-077).

Fixture-only validation (network-free, non-authorizing)::

    python scripts/ops/legal_data/audit_legal_source_rights.py --fixture-only --check

Live evidence validation (LCR-078; fails closed when the live catalog is absent)::

    python scripts/ops/legal_data/audit_legal_source_rights.py --require-live-source-evidence --check

Design invariants
-----------------
* Fixture-only success is explicitly non-authorizing for publication.
* Live mode requires a sealed live catalog with authorizing_for_publication=true.
* The policy evaluator is the sole admission authority; card labels never admit.
* Unknown, prohibited, stale, scope-mismatched, or unsupported evidence fails closed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.legal_source_rights_policy import (
    CATALOG_SCHEMA_VERSION,
    CURRENTNESS_DISCLAIMER,
    GOAL_ID,
    PRODUCER as POLICY_PRODUCER,
    SCHEMA_VERSION,
    TASK_ID,
    LegalSourceRightsPolicyError,
    LiveEvidenceRequiredError,
    audit_fixture_catalog,
    default_fixture_catalog_path,
    default_live_catalog_path,
    default_schema_path,
    evaluate_catalog,
    format_utc_timestamp,
    require_live_source_evidence,
    sha256_json,
)

PRODUCER = "audit_legal_source_rights.py"
REPORT_SCHEMA = "ipfs_datasets_py/legal-source-rights-compliance@1"
CODE_VERSION = "1"


class AuditError(RuntimeError):
    """Raised when the rights audit cannot complete fail-closed."""


def _print_json(payload: Mapping[str, Any]) -> None:
    sys.stdout.write(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )


def run_fixture_check(
    *,
    catalog_path: Optional[Path] = None,
    schema_path: Optional[Path] = None,
) -> dict[str, Any]:
    """Validate the sealed fixture catalog and return a non-authorizing report."""

    try:
        report = audit_fixture_catalog(
            catalog_path=catalog_path,
            schema_path=schema_path,
        )
    except LegalSourceRightsPolicyError as exc:
        raise AuditError(str(exc)) from exc

    report = dict(report)
    report.update(
        {
            "report_schema": REPORT_SCHEMA,
            "code_version": CODE_VERSION,
            "audit_producer": PRODUCER,
            "policy_producer": POLICY_PRODUCER,
            "program_id": "legal-corpora-reindex-v1",
            "mode": "fixture_only",
            "authorizing_for_publication": False,
            "fixture_only_non_authorizing": True,
            "status": "passed",
            "acceptance": {
                "distinguishes_government_from_presentation_annotations_editorial_database": True,
                "deny_on_unknown": True,
                "card_label_alone_not_authority": True,
                "fixture_only_non_authorizing": True,
                "admitted_count": report["admitted_count"],
                "denied_count": report["denied_count"],
            },
            "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        }
    )
    report["report_digest_sha256"] = sha256_json(
        {k: v for k, v in report.items() if k != "report_digest_sha256"}
    )
    return report


def run_live_check(
    *,
    catalog_path: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Validate the live rights catalog (LCR-078 entry point).

    Fails closed when the live catalog is missing, non-live, or non-authorizing.
    """

    try:
        catalog = require_live_source_evidence(catalog_path=catalog_path)
    except LiveEvidenceRequiredError as exc:
        raise AuditError(str(exc)) from exc
    except LegalSourceRightsPolicyError as exc:
        raise AuditError(str(exc)) from exc

    verifier_now = now if now is not None else datetime.now(timezone.utc)
    evaluation = evaluate_catalog(
        catalog,
        now=verifier_now,
        authorizing_mode=True,
    )
    if evaluation["denied_count"] != 0:
        # Live catalogs may include quarantined scopes; only *default-release*
        # admitted scopes are required to pass. Deny non-quarantine unexpected
        # denials among scopes that claim allowed disposition.
        unexpected = [
            d
            for d in evaluation["decisions"]
            if (not d["admitted"])
            and d["rights_disposition"] == "allowed"
            and "presentation_or_enhancement_scope" not in d.get("reason_codes", [])
        ]
        # For live mode under LCR-078, the catalog may still list quarantine
        # scopes. Fail only when an allowed government/statutory claim is denied.
        if unexpected:
            raise AuditError(
                "live catalog has unexpected denials for allowed dispositions:\n- "
                + "\n- ".join(
                    f"{d['record_id']}: {','.join(d['reason_codes'])}" for d in unexpected
                )
            )

    if evaluation["admitted_count"] < 1:
        raise AuditError("live catalog must admit at least one government/statutory scope")

    report = dict(evaluation)
    report.update(
        {
            "report_schema": REPORT_SCHEMA,
            "code_version": CODE_VERSION,
            "audit_producer": PRODUCER,
            "policy_producer": POLICY_PRODUCER,
            "program_id": "legal-corpora-reindex-v1",
            "mode": "live",
            "status": "passed",
            "verified_at": format_utc_timestamp(verifier_now),
            "catalog_path": str(
                (Path(catalog_path) if catalog_path else default_live_catalog_path()).as_posix()
            ),
            "acceptance": {
                "live_source_evidence_required": True,
                "deny_on_unknown": True,
                "card_label_alone_not_authority": True,
                "admitted_count": evaluation["admitted_count"],
                "denied_count": evaluation["denied_count"],
            },
            "currentness_disclaimer": CURRENTNESS_DISCLAIMER,
        }
    )
    report["report_digest_sha256"] = sha256_json(
        {k: v for k, v in report.items() if k != "report_digest_sha256"}
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Audit legal source-rights admission (LCR-077). "
            "Fixture-only success is non-authorizing."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--fixture-only",
        action="store_true",
        help="Validate the sealed fixture catalog offline (non-authorizing).",
    )
    mode.add_argument(
        "--require-live-source-evidence",
        action="store_true",
        help=(
            "Require the live sealed catalog and evaluate with a trusted clock "
            "(LCR-078). Fails closed when live evidence is missing."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run validation and exit non-zero on failure (default behavior).",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="Override catalog path (fixture or live depending on mode).",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=None,
        help="Override JSON schema path (fixture mode).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the full audit report as JSON on stdout.",
    )
    parser.add_argument(
        "--write-receipt",
        type=Path,
        default=None,
        help=(
            "Optional path to write the compliance receipt JSON. "
            "Fixture mode writes are marked non-authorizing."
        ),
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    # --check is the default validation posture for both modes.
    _ = args.check  # accepted for CLI compatibility with the task contract

    try:
        if args.fixture_only:
            catalog_path = args.catalog or default_fixture_catalog_path()
            schema_path = args.schema or default_schema_path()
            report = run_fixture_check(
                catalog_path=catalog_path,
                schema_path=schema_path,
            )
        else:
            catalog_path = args.catalog or default_live_catalog_path()
            report = run_live_check(catalog_path=catalog_path)
    except AuditError as exc:
        error_payload = {
            "status": "failed",
            "task_id": TASK_ID,
            "goal_id": GOAL_ID,
            "schema_version": SCHEMA_VERSION,
            "catalog_schema_version": CATALOG_SCHEMA_VERSION,
            "error": str(exc),
            "authorizing_for_publication": False,
        }
        if args.json:
            _print_json(error_payload)
        else:
            sys.stderr.write(f"audit_legal_source_rights: FAILED: {exc}\n")
        return 1
    except Exception as exc:  # noqa: BLE001 - fail closed on unexpected errors
        sys.stderr.write(f"audit_legal_source_rights: FAILED (unexpected): {exc}\n")
        return 1

    if args.write_receipt is not None:
        receipt_path = Path(args.write_receipt)
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if args.json:
        _print_json(report)
    else:
        mode = report.get("mode", "unknown")
        sys.stdout.write(
            f"audit_legal_source_rights: PASSED ({mode})\n"
            f"  task_id={TASK_ID} goal_id={GOAL_ID}\n"
            f"  admitted={report.get('admitted_count')} "
            f"denied={report.get('denied_count')}\n"
            f"  authorizing_for_publication="
            f"{report.get('authorizing_for_publication')}\n"
            f"  catalog_digest={report.get('catalog_digest_sha256')}\n"
        )
        if mode == "fixture_only":
            sys.stdout.write(
                "  note: fixture-only success is non-authorizing for publication\n"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
