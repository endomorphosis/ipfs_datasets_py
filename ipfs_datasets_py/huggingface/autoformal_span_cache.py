"""Flush the sealed autoformal span cache to Hugging Face parquet.

DuckDB remains the live cache. Parquet is an export. JSONL is not written.
Dry-run planning never contacts a write endpoint. A sealed compile is not
a legal admit.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ipfs_datasets_py.huggingface.publication_profile import (
    BASE_PROHIBITED_OPERATIONS,
    DEFAULT_REPOSITORY_TYPE,
    DEFAULT_TARGET_REVISION,
    HuggingFacePublicationProfile,
)


PACKAGE_SCHEMA = "uscode-autoformal-span-cache-package/v1"
POINTER_SCHEMA = "ipfs_datasets_py/autoformal-span-cache-release-pointer/v1"
SPANS_NAME = "sealed-spans.parquet"
MANIFEST_NAME = "release-manifest.json"
POINTER_NAME = "pointer.json"
DEFAULT_REPOSITORY_ID = "justicedao/uscode-autoformal-span-cache"


class AutoformalSpanCacheError(ValueError):
    """Unsafe or incomplete sealed-span Hugging Face package."""


def autoformal_span_cache_publication_profile(
    *,
    repository_id: str = DEFAULT_REPOSITORY_ID,
) -> HuggingFacePublicationProfile:
    return HuggingFacePublicationProfile(
        profile_id="autoformal-span-cache",
        program_id="uscode-autoformal-span-cache",
        goal_id="AFTD-G000",
        plan_schema_version="autoformal-span-cache-hf-publication-plan/v1",
        receipt_schema_version="autoformal-span-cache-hf-publication-receipt/v1",
        canonical_release_schema="autoformal-span-cache-huggingface-release/v1",
        repository_id=repository_id,
        repository_type=DEFAULT_REPOSITORY_TYPE,
        release_prefix_template="data/autoformal_span_cache/{release_id}",
        pointer_path="runtime/autoformal-span-cache-release-pointer.json",
        target_revision=DEFAULT_TARGET_REVISION,
        commit_message="autoformal-span-cache: append-only sealed compile receipts",
        prohibited_operations=BASE_PROHIBITED_OPERATIONS,
        require_pinned_verification_before_promotion=True,
        allow_remote_write_on_dry_run=False,
        metadata={
            "legacy_profile": False,
            "program": "uscode-autoformal-span-cache",
            "track": "sealed-compile-cache",
            "jsonl_written": False,
        },
    )


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def build_span_cache_package(
    rows: Sequence[Mapping[str, Any]],
    destination: str | Path,
    *,
    repository_id: str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Write sealed-span parquet. JSONL is not written."""

    import pyarrow as pa
    import pyarrow.parquet as pq

    root = Path(destination)
    root.mkdir(parents=True, exist_ok=True)
    records = []
    for row in rows:
        records.append(
            {
                "admitted": False,
                "code_identity": str(row.get("code_identity") or ""),
                "decompiled": str(row.get("decompiled") or ""),
                "formalized": False,
                "legal_id": str(row.get("legal_id") or ""),
                "sealed": True,
                "source_sha256": str(row.get("source_sha256") or ""),
                "source_span_id": str(row.get("source_span_id") or ""),
                "source_text": str(row.get("source_text") or ""),
                "term_ids": json.dumps(list(row.get("term_ids") or []), ensure_ascii=True, sort_keys=True),
            }
        )
    table = pa.Table.from_pylist(records) if records else pa.table(
        {
            "admitted": pa.array([], type=pa.bool_()),
            "code_identity": pa.array([], type=pa.string()),
            "decompiled": pa.array([], type=pa.string()),
            "formalized": pa.array([], type=pa.bool_()),
            "legal_id": pa.array([], type=pa.string()),
            "sealed": pa.array([], type=pa.bool_()),
            "source_sha256": pa.array([], type=pa.string()),
            "source_span_id": pa.array([], type=pa.string()),
            "source_text": pa.array([], type=pa.string()),
            "term_ids": pa.array([], type=pa.string()),
        }
    )
    parquet_path = root / SPANS_NAME
    pq.write_table(table, parquet_path)
    payload = parquet_path.read_bytes()
    rid = release_id or ("span-cache-" + _sha(payload)[:12])
    repo = repository_id or DEFAULT_REPOSITORY_ID
    parquet_info = {
        "path": SPANS_NAME,
        "relative_path": SPANS_NAME,
        "sha256": _sha(payload),
        "size_bytes": len(payload),
    }
    manifest = {
        "admitted": False,
        "files": [parquet_info],
        "formalized": False,
        "jsonl_written": False,
        "package_schema": PACKAGE_SCHEMA,
        "release_id": rid,
        "repository_id": repo,
        "row_count": table.num_rows,
        "schema_version": "autoformal-span-cache-huggingface-release/v1",
        "sealed_spans_path": SPANS_NAME,
        "sealed_spans_sha256": parquet_info["sha256"],
        "wrote_compiler": False,
    }
    manifest["release_sha256"] = _sha(
        _json({key: value for key, value in manifest.items() if key != "release_sha256"})
    )
    (root / MANIFEST_NAME).write_bytes(_json(manifest))
    pointer = {
        "jsonl_written": False,
        "manifest_path": str(root / MANIFEST_NAME),
        "package_root": str(root),
        "release_id": rid,
        "schema": POINTER_SCHEMA,
        "sealed_spans_path": str(parquet_path),
    }
    (root / POINTER_NAME).write_bytes(_json(pointer))
    return {
        "admitted": False,
        "formalized": False,
        "jsonl_written": False,
        "local_root": str(root),
        "manifest": manifest,
        "package_root": str(root),
        "pointer": pointer,
        "row_count": table.num_rows,
        "uploaded": False,
    }


def flush_span_cache(
    rows: Sequence[Mapping[str, Any]],
    destination: str | Path,
    *,
    dry_run: bool = True,
    publisher: Any | None = None,
    approval: Any | None = None,
    repository_id: str | None = None,
    release_id: str | None = None,
) -> dict[str, Any]:
    """Package sealed spans. Live publish needs PublicationApproval."""

    package = build_span_cache_package(
        rows, destination, repository_id=repository_id, release_id=release_id
    )
    profile = autoformal_span_cache_publication_profile(
        repository_id=package["manifest"]["repository_id"]
    )
    if publisher is None:
        from ipfs_datasets_py.huggingface.publisher import HuggingFaceReleasePublisher

        publisher = HuggingFaceReleasePublisher(profile=profile)
    plan = publisher.plan_dry_run(package["manifest"], local_root=package["local_root"])
    receipt = {
        **package,
        "dry_run": True,
        "plan_digest": getattr(plan, "plan_digest", ""),
        "remote_write_contacted": False,
        "uploaded": False,
    }
    if dry_run:
        return receipt
    if approval is None:
        raise AutoformalSpanCacheError(
            "live Hugging Face span-cache publication requires an explicit approved publish path"
        )
    publish = getattr(publisher, "publish_append_only", None)
    if not callable(publish):
        raise AutoformalSpanCacheError(
            "live Hugging Face span-cache publication requires publisher.publish_append_only"
        )
    commit = publish(plan, approval=approval, local_root=package["local_root"])
    receipt["uploaded"] = True
    receipt["dry_run"] = False
    receipt["commit"] = getattr(commit, "commit_sha", "") or ""
    return receipt
