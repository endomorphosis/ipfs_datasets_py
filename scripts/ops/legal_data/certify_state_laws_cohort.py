#!/usr/bin/env python3
"""Certify isolated state-law scrape cohort receipts (LCR-007).

Validates that a cohort receipt covers the exact sealed jurisdiction set for
the requested cohort letter(s), that every jurisdiction is success-eligible,
that partial-success was not promoted, and that the run did not claim a
production upload or shared combined overwrite.

Offline usage:

    python scripts/ops/legal_data/certify_state_laws_cohort.py --cohort A --check
    python scripts/ops/legal_data/certify_state_laws_cohort.py --cohorts A,B,C,D --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "LCR-007"
GOAL_ID = "LCR-G010"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "certify_state_laws_cohort.py"
CERT_SCHEMA = "ipfs_datasets_py/legal-corpora-reindex-cohort-certification@1"


class CohortCertifyError(RuntimeError):
    """Raised when cohort certification cannot complete fail-closed."""


def _load_runner_module():
    path = Path(__file__).with_name("run_legal_corpora_reindex_cohort.py")
    if not path.is_file():
        raise CohortCertifyError(f"cohort runner missing: {path}")
    name = "lcr007_run_legal_corpora_reindex_cohort"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise CohortCertifyError(f"unable to load cohort runner: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def parse_cohort_list(value: str) -> List[str]:
    raw = str(value or "").strip()
    if not raw:
        raise CohortCertifyError("at least one cohort letter is required")
    parts = [p.strip().upper() for p in raw.replace(" ", ",").split(",") if p.strip()]
    if not parts:
        raise CohortCertifyError("at least one cohort letter is required")
    return parts


def load_receipt(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        raise CohortCertifyError(f"cohort receipt missing: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CohortCertifyError(f"invalid receipt JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CohortCertifyError(f"receipt root must be object: {path}")
    return payload


def certify_cohort_receipt(
    receipt: Mapping[str, Any],
    *,
    cohort: str,
    runner: Any | None = None,
) -> Dict[str, Any]:
    """Certify one cohort receipt against the sealed jurisdiction set."""
    mod = runner or _load_runner_module()
    cohort_key = str(cohort).strip().upper()
    expected = mod.cohort_states(cohort_key)
    findings: List[str] = []

    observed_states = [str(s).upper() for s in (receipt.get("states") or [])]
    if not observed_states and isinstance(receipt.get("state_results"), Mapping):
        observed_states = sorted(str(s).upper() for s in receipt["state_results"].keys())

    if set(observed_states) != set(expected):
        missing = sorted(set(expected) - set(observed_states))
        extra = sorted(set(observed_states) - set(expected))
        findings.append(
            f"jurisdiction set mismatch for cohort {cohort_key}: "
            f"missing={missing}; extra={extra}"
        )
    if cohort_key == "M" and "DC" not in observed_states and "DC" in expected:
        findings.append("cohort M receipt omits DC")

    state_results = receipt.get("state_results")
    if not isinstance(state_results, Mapping):
        findings.append("state_results missing")
        state_results = {}

    for state in expected:
        entry = state_results.get(state) if isinstance(state_results, Mapping) else None
        if not isinstance(entry, Mapping):
            findings.append(f"{state}: missing state result")
            continue
        status = mod.promote_state_status(str(entry.get("status") or ""))
        if status != "success":
            findings.append(f"{state}: status={status} (not success)")
        if bool(entry.get("partial_checkpoint_promoted")):
            findings.append(f"{state}: partial checkpoint promoted")
        if bool(entry.get("timeout_promoted_to_success")):
            findings.append(f"{state}: timeout promoted to success")
        if int(entry.get("failed_final") or 0) != 0:
            findings.append(f"{state}: failed_final={entry.get('failed_final')}")

    if not mod.cohort_success_allowed(state_results) and not findings:
        findings.append("cohort_success_allowed returned false")

    if bool(receipt.get("production_upload")):
        findings.append("receipt claims production_upload")
    if bool(receipt.get("shared_combined_write")):
        findings.append("receipt claims shared_combined_write")

    # Receipt must not leak secrets.
    serialized = json.dumps(receipt, default=str)
    for needle in ("hf_", "Bearer ", "/home/", "api_key"):
        # Allow schema strings; flag obvious secret material.
        if needle == "hf_" and "hf_token" in serialized.lower():
            if "[REDACTED]" not in serialized and "hf_" in serialized:
                # only fail when a non-redacted token-looking value appears
                import re

                if re.search(r"hf_[A-Za-z0-9]{8,}", serialized):
                    findings.append("receipt appears to contain hf_ token material")
        elif needle == "/home/" and "/home/" in serialized:
            findings.append("receipt contains absolute /home/ path")
        elif needle == "Bearer " and "Bearer " in serialized:
            findings.append("receipt contains Bearer token material")

    status = "pass" if not findings else "fail"
    return {
        "cohort": cohort_key,
        "status": status,
        "expected_states": expected,
        "observed_states": observed_states,
        "findings": findings,
        "production_upload": bool(receipt.get("production_upload")),
        "shared_combined_write": bool(receipt.get("shared_combined_write")),
    }


def certify_cohorts(
    cohorts: Sequence[str],
    *,
    receipt_dir: Optional[Path] = None,
    fixture_only: bool = False,
    runner: Any | None = None,
) -> Dict[str, Any]:
    """Certify one or more cohorts. In fixture-only mode, generate receipts first."""
    mod = runner or _load_runner_module()
    cohort_list = [str(c).strip().upper() for c in cohorts]
    for c in cohort_list:
        mod.cohort_states(c)  # validate

    results: List[Dict[str, Any]] = []
    generated_roots: List[str] = []

    if fixture_only or receipt_dir is None:
        # Generate isolated fixture receipts via the runner, then certify.
        for cohort in cohort_list:
            run = mod.run_cohort(cohort=cohort, fixture_only=False, resume=False)
            generated_roots.append(str(run.get("run_root") or ""))
            receipt_path = Path(str(run.get("cohort_receipt_path") or ""))
            receipt = load_receipt(receipt_path)
            results.append(
                certify_cohort_receipt(receipt, cohort=cohort, runner=mod)
            )
    else:
        root = Path(receipt_dir).expanduser().resolve()
        for cohort in cohort_list:
            # Accept either direct file or directory layout from the runner.
            candidates = [
                root / f"cohort-{cohort}.json",
                root / "receipts" / f"cohort-{cohort}.json",
                root / cohort / f"cohort-{cohort}.json",
            ]
            receipt_path = next((p for p in candidates if p.is_file()), None)
            if receipt_path is None:
                results.append(
                    {
                        "cohort": cohort,
                        "status": "fail",
                        "expected_states": mod.cohort_states(cohort),
                        "observed_states": [],
                        "findings": [f"no receipt found under {root} for cohort {cohort}"],
                        "production_upload": False,
                        "shared_combined_write": False,
                    }
                )
                continue
            receipt = load_receipt(receipt_path)
            results.append(certify_cohort_receipt(receipt, cohort=cohort, runner=mod))

    failed = [r for r in results if r.get("status") != "pass"]
    return {
        "schema": CERT_SCHEMA,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "program_id": PROGRAM_ID,
        "producer": PRODUCER,
        "status": "pass" if not failed else "fail",
        "cohorts": cohort_list,
        "results": results,
        "pass_count": len(results) - len(failed),
        "fail_count": len(failed),
        "generated_run_roots": generated_roots,
        "includes_dc_in_map": "DC" in mod.COHORT_JURISDICTIONS.get("M", ()),
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Certify state-law reindex cohort receipts (LCR-007)"
    )
    parser.add_argument("--cohort", default="", help="Single cohort letter A–M")
    parser.add_argument(
        "--cohorts",
        default="",
        help="Comma-separated cohort letters (e.g. A,B,C,D)",
    )
    parser.add_argument(
        "--receipt-dir",
        default="",
        help="Directory containing cohort-*.json receipts",
    )
    parser.add_argument(
        "--fixture-only",
        action="store_true",
        help="Generate offline fixture receipts then certify them",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero unless certification passes",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.cohorts:
            cohorts = parse_cohort_list(args.cohorts)
        elif args.cohort:
            cohorts = parse_cohort_list(args.cohort)
        else:
            raise CohortCertifyError("pass --cohort or --cohorts")
        # Default to fixture generation when no receipt dir is given so
        # `certify_state_laws_cohort.py --cohort A --check` is offline-safe.
        fixture_only = bool(args.fixture_only) or not str(args.receipt_dir or "").strip()
        report = certify_cohorts(
            cohorts,
            receipt_dir=Path(args.receipt_dir) if args.receipt_dir else None,
            fixture_only=fixture_only,
        )
    except CohortCertifyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json or args.check or args.fixture_only:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print(f"status: {report.get('status')}")
        print(f"cohorts: {','.join(report.get('cohorts') or [])}")
        print(f"pass_count: {report.get('pass_count')}")
        print(f"fail_count: {report.get('fail_count')}")

    ok = report.get("status") == "pass"
    if args.check and not ok:
        print("RESULT: FAIL", file=sys.stderr)
        return 1
    if args.check:
        print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
