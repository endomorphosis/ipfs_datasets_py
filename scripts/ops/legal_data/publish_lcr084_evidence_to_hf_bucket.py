#!/usr/bin/env python3
"""Publish LCR-084 fail-closed evidence additively to justicedao/open-us-law-bucket.

Writes only under ``legal-corpora-reindex/lcr-084/<receipt_sha256>/``.
Does not mutate dataset repos, OUL parquet roots, or LATEST.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

import scripts.ops.legal_data.audit_legal_corpora_hugging_face_mutation_paths as mutation  # noqa: E402
import scripts.ops.legal_data.audit_state_laws_full_scrape_acceptance as scrape  # noqa: E402
import scripts.ops.legal_data.inventory_lcr084_bucket_statutes as inventory  # noqa: E402

TASK_ID = "LCR-084"
GOAL_ID = "LCR-G146"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "publish_lcr084_evidence_to_hf_bucket.py"
SCHEMA = "ipfs_datasets_py/lcr084-hf-bucket-publication@1"
AUTHORIZED_BUCKET_ID = "justicedao/open-us-law-bucket"
FORBIDDEN_REPOS = frozenset(
    {"justicedao/ipfs_state_laws", "justicedao/ipfs_federal_register"}
)
PREFIX_HEAD = "legal-corpora-reindex/lcr-084"
RECEIPT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/lcr084_bucket_publication.json"
)


class BucketPublishError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hf_uri(path: str) -> str:
    return f"hf://buckets/{AUTHORIZED_BUCKET_ID}/{path}"


def build_plan() -> dict[str, Any]:
    scrape_report = scrape.inspect_full_scrape_acceptance(
        require_live_official=False,
        require_jurisdictions=51,
        require_production_candidate=False,
    )
    mutation_report = mutation.inventory_mutation_paths()
    try:
        inventory_report = inventory.list_bucket_statute_codes()
    except inventory.InventoryError as exc:
        inventory_report = {"status": "blocked", "error": str(exc)}
    bundle = {
        "scrape_acceptance": scrape_report,
        "mutation_paths": {
            "status": mutation_report.get("status"),
            "unprotected_count": mutation_report.get("unprotected_count"),
            "callsite_count": mutation_report.get("callsite_count"),
            "unprotected_callsites": mutation_report.get("unprotected_callsites"),
            "reasons": mutation_report.get("reasons"),
        },
        "bucket_statute_inventory": inventory_report,
        "authorizing_for_publication": False,
        "authorizing_hub_upload": False,
        "satisfies_exact_51_official": False,
    }
    encoded = json.dumps(bundle, sort_keys=True).encode("utf-8")
    digest = _sha256_bytes(encoded)
    prefix = f"{PREFIX_HEAD}/{digest}"
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "bucket_id": AUTHORIZED_BUCKET_ID,
        "bucket_url": f"https://huggingface.co/buckets/{AUTHORIZED_BUCKET_ID}",
        "prefix": prefix,
        "bundle_sha256": digest,
        "bundle": bundle,
        "objects": [
            {
                "name": "lcr084_evidence_bundle.json",
                "remote_path": f"{prefix}/lcr084_evidence_bundle.json",
            }
        ],
        "status": "planned",
        "mode": "dry",
    }


def _run_hf_cp_bytes(data: bytes, remote_uri: str) -> None:
    completed = subprocess.run(
        ["hf", "buckets", "cp", "-", remote_uri],
        input=data,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or b"").decode("utf-8", "replace")
        raise BucketPublishError(f"hf buckets cp failed: {err[:800]}")


def publish_live(plan: Mapping[str, Any]) -> dict[str, Any]:
    if str(plan.get("bucket_id")) != AUTHORIZED_BUCKET_ID:
        raise BucketPublishError("bucket is not authorized")
    payload = json.dumps(plan["bundle"], indent=2, sort_keys=True).encode("utf-8") + b"\n"
    remote = str(plan["objects"][0]["remote_path"])
    if not remote.startswith(PREFIX_HEAD + "/"):
        raise BucketPublishError("remote path escapes LCR-084 prefix")
    _run_hf_cp_bytes(payload, _hf_uri(remote))
    result = dict(plan)
    result["mode"] = "live"
    result["status"] = "uploaded"
    result["uploaded"] = [{"uri": _hf_uri(remote), "bytes": len(payload)}]
    return result


def write_receipt(payload: Mapping[str, Any]) -> Path:
    target = REPOSITORY_ROOT / RECEIPT_RELPATH
    snapshot = dict(payload)
    # Keep the local receipt compact: drop the nested bundle copy.
    snapshot.pop("bundle", None)
    target.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish LCR-084 evidence to the Open US Law bucket")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--bucket", default=AUTHORIZED_BUCKET_ID)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if str(args.bucket) != AUTHORIZED_BUCKET_ID:
            raise BucketPublishError(f"only {AUTHORIZED_BUCKET_ID} is authorized")
        if str(args.bucket) in FORBIDDEN_REPOS:
            raise BucketPublishError("refusing protected dataset repository")
        plan = build_plan()
        result = publish_live(plan) if args.live else plan
        if args.write:
            path = write_receipt(result)
            sys.stderr.write(f"wrote {path.as_posix()}\n")
        if args.json:
            sys.stdout.write(json.dumps({k: v for k, v in result.items() if k != "bundle"}, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(
                f"publish_lcr084_evidence_to_hf_bucket: {result['status'].upper()} "
                f"prefix={result['prefix']}\n"
            )
        return 0
    except BucketPublishError as exc:
        sys.stderr.write(f"publish_lcr084_evidence_to_hf_bucket: FAILED: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
