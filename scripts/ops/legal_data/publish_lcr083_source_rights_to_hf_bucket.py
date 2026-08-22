#!/usr/bin/env python3
"""Publish sealed LCR-083 source-rights evidence to the Open US Law bucket.

Additive-only. Target is ``justicedao/open-us-law-bucket`` under
``legal-corpora-reindex/lcr-083/<receipt_digest>/``. This does **not**
mutate ``justicedao/ipfs_state_laws`` or ``justicedao/ipfs_federal_register``,
does not overwrite OUL parquet roots, and does not update ``LATEST.json``.

Default is a dry plan. Live upload is ``--live``.

Validation::

    python scripts/ops/legal_data/publish_lcr083_source_rights_to_hf_bucket.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

TASK_ID = "LCR-083"
GOAL_ID = "LCR-G145"
PROGRAM_ID = "legal-corpora-reindex-v1"
PRODUCER = "publish_lcr083_source_rights_to_hf_bucket.py"
SCHEMA = "ipfs_datasets_py/lcr083-hf-bucket-publication@1"
AUTHORIZED_BUCKET_ID = "justicedao/open-us-law-bucket"
FORBIDDEN_REPOS = frozenset(
    {
        "justicedao/ipfs_state_laws",
        "justicedao/ipfs_federal_register",
    }
)
PREFIX_HEAD = "legal-corpora-reindex/lcr-083"
CATALOG_RELPATH = Path("data/legal/legal_source_rights_catalog.json")
COMPLIANCE_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/legal_source_rights_compliance.json"
)
RECEIPT_RELPATH = Path(
    "docs/reports/legal_corpora_reindex/lcr083_bucket_publication.json"
)
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
PROTECTED_ROOT_PREFIXES = (
    "us_",
    "releases/",
    "LATEST.json",
    ".gitattributes",
    "README.md",
    "SHA256SUMS.json",
)


class BucketPublishError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise BucketPublishError(f"required evidence missing: {path.as_posix()}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if type(payload) is not dict:
        raise BucketPublishError(f"evidence root must be an object: {path.as_posix()}")
    return payload


def _hf_uri(bucket_id: str, path: str) -> str:
    return f"hf://buckets/{bucket_id}/{path}"


def build_plan(*, repository_root: Path = REPOSITORY_ROOT) -> dict[str, Any]:
    catalog_path = repository_root / CATALOG_RELPATH
    compliance_path = repository_root / COMPLIANCE_RELPATH
    catalog_bytes = catalog_path.read_bytes()
    compliance_bytes = compliance_path.read_bytes()
    catalog = _load_json(catalog_path)
    compliance = _load_json(compliance_path)
    receipt_digest = str(compliance.get("report_digest_sha256") or "").strip()
    catalog_digest = str(compliance.get("catalog_digest_sha256") or "").strip()
    if DIGEST_RE.fullmatch(receipt_digest) is None:
        raise BucketPublishError("compliance receipt_digest is not a 64-hex digest")
    if DIGEST_RE.fullmatch(catalog_digest) is None:
        raise BucketPublishError("compliance catalog_digest is not a 64-hex digest")
    catalog_bytes_digest = _sha256_bytes(catalog_bytes)
    compliance_bytes_digest = _sha256_bytes(compliance_bytes)
    prefix = f"{PREFIX_HEAD}/{receipt_digest}"
    objects = [
        {
            "local_relpath": CATALOG_RELPATH.as_posix(),
            "remote_path": f"{prefix}/legal_source_rights_catalog.json",
            "sha256": catalog_bytes_digest,
            "bytes": len(catalog_bytes),
        },
        {
            "local_relpath": COMPLIANCE_RELPATH.as_posix(),
            "remote_path": f"{prefix}/legal_source_rights_compliance.json",
            "sha256": compliance_bytes_digest,
            "bytes": len(compliance_bytes),
        },
    ]
    for item in objects:
        remote = str(item["remote_path"])
        if not remote.startswith(f"{PREFIX_HEAD}/"):
            raise BucketPublishError(f"remote path escapes LCR-083 prefix: {remote}")
        if any(remote.startswith(p) or remote == p.rstrip("/") for p in PROTECTED_ROOT_PREFIXES):
            raise BucketPublishError(f"refusing protected OUL root path {remote}")
        if ".." in remote.split("/"):
            raise BucketPublishError(f"remote path is unsafe: {remote}")
    return {
        "schema": SCHEMA,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "task_id": TASK_ID,
        "goal_id": GOAL_ID,
        "bucket_id": AUTHORIZED_BUCKET_ID,
        "bucket_url": f"https://huggingface.co/buckets/{AUTHORIZED_BUCKET_ID}",
        "prefix": prefix,
        "catalog_digest_sha256": catalog_digest,
        "receipt_digest_sha256": receipt_digest,
        "catalog_bytes_sha256": catalog_bytes_digest,
        "compliance_bytes_sha256": compliance_bytes_digest,
        "authorizing_hub_dataset_upload": False,
        "forbidden_repos": sorted(FORBIDDEN_REPOS),
        "additive": True,
        "objects": objects,
        "uris": [_hf_uri(AUTHORIZED_BUCKET_ID, item["remote_path"]) for item in objects],
    }


def _run_hf_cp(local: Path, remote_uri: str) -> None:
    cmd = ["hf", "buckets", "cp", str(local), remote_uri]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise BucketPublishError(f"hf CLI is unavailable: {exc}") from exc
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        raise BucketPublishError(f"hf buckets cp failed for {remote_uri}: {err[:800]}")


def publish_live(
    plan: Mapping[str, Any],
    *,
    repository_root: Path = REPOSITORY_ROOT,
) -> dict[str, Any]:
    bucket_id = str(plan["bucket_id"])
    if bucket_id != AUTHORIZED_BUCKET_ID:
        raise BucketPublishError(f"bucket {bucket_id!r} is not authorized")
    if bucket_id in FORBIDDEN_REPOS:
        raise BucketPublishError("refusing protected dataset repository")
    uploaded: list[dict[str, Any]] = []
    for item in plan["objects"]:
        local = repository_root / str(item["local_relpath"])
        remote = str(item["remote_path"])
        uri = _hf_uri(bucket_id, remote)
        _run_hf_cp(local, uri)
        uploaded.append({"uri": uri, "sha256": item["sha256"], "bytes": item["bytes"]})
    result = dict(plan)
    result["mode"] = "live"
    result["status"] = "uploaded"
    result["uploaded"] = uploaded
    return result


def write_receipt(payload: Mapping[str, Any], *, repository_root: Path = REPOSITORY_ROOT) -> Path:
    target = repository_root / RECEIPT_RELPATH
    target.parent.mkdir(parents=True, exist_ok=True)
    snapshot = dict(payload)
    body = {k: v for k, v in snapshot.items() if k != "receipt_sha256"}
    encoded = json.dumps(body, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    snapshot["receipt_sha256"] = _sha256_bytes(encoded)
    target.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Publish LCR-083 evidence to the Open US Law bucket")
    parser.add_argument("--check", action="store_true", help="Validate the dry plan only")
    parser.add_argument("--live", action="store_true", help="Perform additive bucket upload")
    parser.add_argument("--write", action="store_true", help="Write the local publication receipt")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--bucket",
        default=AUTHORIZED_BUCKET_ID,
        help="Must remain justicedao/open-us-law-bucket",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if str(args.bucket) != AUTHORIZED_BUCKET_ID:
            raise BucketPublishError(
                f"only {AUTHORIZED_BUCKET_ID} is authorized; refused {args.bucket!r}"
            )
        if str(args.bucket) in FORBIDDEN_REPOS:
            raise BucketPublishError("refusing protected dataset repository")
        plan = build_plan()
        if args.live:
            result = publish_live(plan)
        else:
            result = dict(plan)
            result["mode"] = "dry"
            result["status"] = "planned"
        if args.write:
            path = write_receipt(result)
            sys.stderr.write(f"wrote {path.as_posix()}\n")
        if args.json:
            sys.stdout.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
        else:
            sys.stdout.write(
                f"publish_lcr083_source_rights_to_hf_bucket: {result['status'].upper()} "
                f"bucket={result['bucket_id']} prefix={result['prefix']}\n"
            )
        if args.check and not args.live:
            return 0
        return 0
    except BucketPublishError as exc:
        sys.stderr.write(f"publish_lcr083_source_rights_to_hf_bucket: FAILED: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
