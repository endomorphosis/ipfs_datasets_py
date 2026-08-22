#!/usr/bin/env python3
"""Inventory justicedao/open-us-law-bucket statute parquets for LCR-084.

This is a recovery/secondary listing only. It cannot satisfy
``--require-live-official`` exact-51 official scrape acceptance.

Never mutates the bucket. Never uploads to dataset repos.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.state_laws_completeness import (  # noqa: E402
    CANONICAL_JURISDICTION_ORDER,
)

TASK_ID = "LCR-084"
GOAL_ID = "LCR-G146"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "inventory_lcr084_bucket_statutes.py"
SCHEMA = "ipfs_datasets_py/lcr084-bucket-statute-inventory@1"
AUTHORIZED_BUCKET_ID = "justicedao/open-us-law-bucket"
REPORT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/lcr084_bucket_statute_inventory.json"
)


class InventoryError(RuntimeError):
    pass


def list_bucket_statute_codes(bucket_id: str = AUTHORIZED_BUCKET_ID) -> dict[str, Any]:
    if bucket_id != AUTHORIZED_BUCKET_ID:
        raise InventoryError(f"only {AUTHORIZED_BUCKET_ID} is authorized for this inventory")
    try:
        completed = subprocess.run(
            ["hf", "buckets", "list", bucket_id],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise InventoryError(f"hf CLI is unavailable: {exc}") from exc
    if completed.returncode != 0:
        raise InventoryError((completed.stderr or completed.stdout or "")[:800])
    files: list[dict[str, str]] = []
    codes: set[str] = set()
    for line in completed.stdout.splitlines():
        text = line.strip()
        if "_statutes.parquet" not in text or "us_" not in text:
            continue
        name = text.rsplit(" ", 1)[-1]
        stem = name.split("/")[-1]
        if not stem.startswith("us_") or not stem.endswith("_statutes.parquet"):
            continue
        code = stem[len("us_") : -len("_statutes.parquet")].upper()
        files.append({"path": stem, "code": code})
        codes.add(code)
    expected = set(CANONICAL_JURISDICTION_ORDER)
    present = {code for code in codes if code in expected}
    extra = sorted(codes - expected)
    missing = [code for code in CANONICAL_JURISDICTION_ORDER if code not in present]
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "bucket_id": bucket_id,
        "bucket_url": f"https://huggingface.co/buckets/{bucket_id}",
        "source_authority_class": "secondary",
        "admission_status": "recovery",
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "satisfies_exact_51_official": False,
        "expected_jurisdictions": list(CANONICAL_JURISDICTION_ORDER),
        "present_expected": sorted(present),
        "missing_expected": missing,
        "extra_codes": extra,
        "statute_files": files,
        "file_count": len(files),
        "reasons": (
            []
            if not missing and not extra
            else [
                "bucket statute parquet listing is recovery-only and is not official live scrape evidence",
                *(
                    [f"missing expected jurisdictions: {missing}"]
                    if missing
                    else []
                ),
                *([f"extra non-exact-51 codes: {extra}"] if extra else []),
            ]
        ),
        "status": "blocked",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LCR-084 recovery inventory of bucket statutes")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    if not args.check:
        sys.stderr.write("inventory_lcr084_bucket_statutes: FAILED: --check is required\n")
        return 2
    try:
        report = list_bucket_statute_codes()
    except InventoryError as exc:
        sys.stderr.write(f"inventory_lcr084_bucket_statutes: FAILED: {exc}\n")
        return 1
    if args.write:
        target = REPOSITORY_ROOT / REPORT_RELPATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        sys.stderr.write(f"wrote {target.as_posix()}\n")
    if args.json:
        sys.stdout.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    else:
        sys.stdout.write(
            "inventory_lcr084_bucket_statutes: "
            f"{report['status'].upper()} present={len(report['present_expected'])}/51 "
            f"missing={report['missing_expected']} extra={report['extra_codes']}\n"
        )
    return 1 if report["status"] != "passed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
