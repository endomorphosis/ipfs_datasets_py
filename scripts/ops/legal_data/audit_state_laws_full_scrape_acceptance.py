#!/usr/bin/env python3
"""Fail-closed LCR-084 state full-scrape acceptance.

The LCR-023 cohort union is untrusted. Production mode rejects fixture,
sampled, two-row cohort F/I reports, and any receipt that is not a fresh
exhaustive official 51-jurisdiction scrape. This CLI never uploads to Hub.

Validation::

    python scripts/ops/legal_data/audit_state_laws_full_scrape_acceptance.py \\
        --require-live-official --require-jurisdictions 51 \\
        --require-production-candidate --check
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

TASK_ID = "LCR-084"
GOAL_ID = "LCR-G146"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "audit_state_laws_full_scrape_acceptance.py"
SCHEMA = "ipfs_datasets_py/state-laws-full-scrape-acceptance@2"
ACCEPTANCE_RELPATH = Path("docs/reports/legal_corpora_reindex/full_scrape_acceptance.json")
CANDIDATE_RELPATH = Path("docs/reports/legal_corpora_reindex/release_candidate.json")
COHORT_F_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_f.json")
COHORT_I_RELPATH = Path("docs/reports/legal_corpora_reindex/cohort_i.json")
TWO_ROW_SYNTHETIC_MAX = 2


class ScrapeAcceptanceError(RuntimeError):
    pass


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ScrapeAcceptanceError(f"required receipt is missing: {path.as_posix()}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScrapeAcceptanceError(f"receipt is not strict JSON: {path.as_posix()}") from exc
    if type(payload) is not dict:
        raise ScrapeAcceptanceError(f"receipt root must be an object: {path.as_posix()}")
    return payload


def _two_row_jurisdictions(cohort: Mapping[str, Any]) -> list[str]:
    receipts = cohort.get("jurisdiction_receipts") or {}
    flagged: list[str] = []
    if not isinstance(receipts, Mapping):
        return flagged
    for code, body in receipts.items():
        if not isinstance(body, Mapping):
            continue
        row_count = int(body.get("row_count") or body.get("statutes_count") or 0)
        discovered = int((body.get("disposition") or {}).get("discovered") or 0)
        if row_count <= TWO_ROW_SYNTHETIC_MAX or discovered <= TWO_ROW_SYNTHETIC_MAX:
            flagged.append(str(code))
    return flagged


def inspect_full_scrape_acceptance(
    *,
    require_live_official: bool,
    require_jurisdictions: int,
    require_production_candidate: bool,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    acceptance = _load(repository_root / ACCEPTANCE_RELPATH)
    candidate = _load(repository_root / CANDIDATE_RELPATH)
    cohort_f = _load(repository_root / COHORT_F_RELPATH)
    cohort_i = _load(repository_root / COHORT_I_RELPATH)

    reasons: list[str] = []
    two_row = {
        "F": _two_row_jurisdictions(cohort_f),
        "I": _two_row_jurisdictions(cohort_i),
    }
    if two_row["F"] or two_row["I"]:
        reasons.append(
            "cohort F/I two-row reports cannot satisfy live official acceptance: "
            f"F={two_row['F']} I={two_row['I']}"
        )
    if acceptance.get("task_id") == "LCR-023":
        reasons.append("LCR-023 union receipt is untrusted synthetic success under LCR-084")
    if acceptance.get("status") == "pass" and acceptance.get("producer") == (
        "state_laws_acquisition_gap_refill.py"
    ):
        reasons.append("gap-refill producer cannot authorize live official production")
    observed = int(acceptance.get("observed_jurisdiction_count") or 0)
    if require_jurisdictions and observed < require_jurisdictions:
        reasons.append(
            f"observed jurisdiction count {observed} < required {require_jurisdictions}"
        )
    candidate_kind = str((candidate.get("candidate") or {}).get("kind") or "")
    if require_production_candidate and (
        candidate.get("fixture_only") is True or "fixture" in candidate_kind
    ):
        reasons.append(f"candidate kind {candidate_kind!r} cannot satisfy production")
    if candidate.get("authorizing_hub_upload") is True:
        reasons.append("candidate authorizing_hub_upload is forbidden")
    if require_live_official and reasons:
        raise ScrapeAcceptanceError("; ".join(reasons))
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "mode": "live_official" if require_live_official else "inspect",
        "status": "passed" if not reasons else "blocked",
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "reasons": reasons,
        "two_row_cohorts": two_row,
        "observed_jurisdiction_count": observed,
        "candidate_kind": candidate_kind,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fail-closed LCR-084 state full-scrape acceptance"
    )
    parser.add_argument("--require-live-official", action="store_true")
    parser.add_argument("--require-jurisdictions", type=int, default=51)
    parser.add_argument("--require-production-candidate", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check:
        sys.stderr.write(
            "audit_state_laws_full_scrape_acceptance: FAILED: --check is required\n"
        )
        return 2
    try:
        report = inspect_full_scrape_acceptance(
            require_live_official=bool(args.require_live_official),
            require_jurisdictions=int(args.require_jurisdictions),
            require_production_candidate=bool(args.require_production_candidate),
        )
    except ScrapeAcceptanceError as exc:
        sys.stderr.write(f"audit_state_laws_full_scrape_acceptance: FAILED: {exc}\n")
        return 1
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "audit_state_laws_full_scrape_acceptance: "
            f"{report['status'].upper()} mode={report['mode']}\n"
        )
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
