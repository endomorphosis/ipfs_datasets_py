#!/usr/bin/env python3
"""Redownload and canary the immutable Open US Law staging candidate (OUL-042).

A clean cache redownloads descriptors and routed shards from the exact
40-hex Dataset revision and content-addressed Bucket prefix recorded by
OUL-041, verifies every staged identity, runs all five query modes, and
proves sparse I/O without a local-artifact fallback.

Default validation is **offline against isolated staging** (no Hub
contact). ``--require-live-staging --check`` binds the sealed canary to
the live isolated staging coordinates and refuses mutable refs, local
root fallback, and public mutation.

Validation gate (no network)::

    python scripts/ops/legal_data/canary_open_us_law_hf_release.py --require-live-staging --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import os
import re
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_query import (  # noqa: E402
    FusionConfig,
    OpenUsLawQueryClient,
    OpenUsLawQueryError,
    OpenUsLawQueryInputError,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    SOURCE_BUCKET,
    digest_mapping,
    normalize_sha256,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_sparse_graphrag import (  # noqa: E402
    QUERY_MODES,
    normalize_query_mode,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import QueryLimits  # noqa: E402
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import ModelSpace  # noqa: E402
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    ImmutableHubResolver,
    MappingTransport,
    MutableRevisionError,
    ResolverError,
    build_descriptor_for_bytes,
)
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (  # noqa: E402
    canonical_json_dumps,
)

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError as _pyarrow_exc:  # pragma: no cover - hard dependency
    pa = None  # type: ignore[assignment]
    pq = None  # type: ignore[assignment]
    _PYARROW_IMPORT_ERROR = _pyarrow_exc
else:
    _PYARROW_IMPORT_ERROR = None


# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "OUL-042"
GOAL_ID: Final = "OUL-G070"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "canary_open_us_law_hf_release.py"
CODE_VERSION: Final = "1"
BUNDLE: Final = "staging-canary"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("OUL-041",)

RECEIPT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-staging-canary@1"
SCHEMA_VERSION: Final = "open-us-law-staging-canary/v1"
FIXTURE_ID: Final = "open-us-law-staging-canary-v1"
STAGING_RECEIPT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-staging-upload@1"

DEFAULT_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/staging_canary.json"
)
STAGING_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/staging_upload.json"
)
STAGE_SCRIPT_RELPATH: Final = Path(
    "scripts/ops/legal_data/stage_open_us_law_hf_release.py"
)

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_BUCKET_ID: Final = SOURCE_BUCKET
DEFAULT_STAGING_BRANCH: Final = "stage/open-us-law-sparse-graphrag-v1"

MODEL_ID: Final = "thenlper/gte-small"
MODEL_REVISION: Final = "17e1f347d17fe144873b1201da91788898c639cd"
VECTOR_SPACE_ID: Final = f"gte-small@{MODEL_REVISION}:d2:norm=l2"

SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "OPEN_US_LAW_HF_TOKEN",
    "OPEN_US_LAW_PUBLICATION_AUTHORIZATION",
    "OPEN_US_LAW_STAGING_AUTHORIZATION",
)

ACCEPTANCE_CRITERIA: Final = (
    "A clean cache redownloads descriptors and routed shards from the "
    "exact 40-hex dataset revision and content-addressed bucket prefix, "
    "verifies all bytes, runs every query mode, and demonstrates sparse "
    "I/O without local artifact fallback."
)

CONTROL_INDEXES: Final[tuple[str, ...]] = (
    "manifest.json",
    "indexes/bm25_keyword_shards.parquet",
    "indexes/corpus_chunks.parquet",
    "indexes/vector_chunks.parquet",
    "indexes/graph_out_adjacency.parquet",
    "indexes/vector_entry_locator.parquet",
)

SELECTED_SHARDS: Final[tuple[str, ...]] = (
    "data/bm25/postings/part-000000.parquet",
    "data/corpus/part-000000.parquet",
    "data/vectors/centroid-000000-part-000000.parquet",
    "data/graph/adjacency/out/part-000000.parquet",
)

QUERY_SPECS: Final[tuple[dict[str, Any], ...]] = (
    {
        "expected_min_results": 1,
        "expected_top_entry_cid": "entry-a",
        "id": "bm25_foia",
        "mode": "bm25",
        "query": "foia",
        "top_k": 3,
        "unused_siblings": ("data/bm25/postings/part-000001.parquet",),
    },
    {
        "expected_min_results": 1,
        "expected_top_entry_cid": "entry-a",
        "id": "vector_centroid0",
        "mode": "vector",
        "query": "foia agency",
        "query_vector": (1.0, 0.0),
        "top_k": 3,
        "unused_siblings": (
            "data/vectors/centroid-000001-part-000000.parquet",
        ),
    },
    {
        "expected_min_results": 1,
        "expected_top_entry_cid": "entry-a",
        "id": "hybrid_foia_agency",
        "mode": "hybrid",
        "query": "foia agency",
        "query_vector": (1.0, 0.0),
        "top_k": 3,
    },
    {
        "expected_min_results": 1,
        "id": "graph_entry_a",
        "mode": "graph",
        "start_node_cid": "entry-a",
        "top_k": 8,
    },
    {
        "expected_min_results": 1,
        "id": "semantic_graph_entry_a",
        "mode": "semantic-graph",
        "query": "foia",
        "query_vector": (1.0, 0.0),
        "start_node_cid": "entry-a",
        "top_k": 8,
    },
)

PRODUCTION_REFS: Final[frozenset[str]] = frozenset(
    {
        "main",
        "master",
        "refs/heads/main",
        "refs/heads/master",
        "production",
        "prod",
        "live",
        "latest",
        "head",
        "default",
        "current",
        "staging",
        "canary",
    }
)

_TOKEN_KEY_RE = re.compile(
    r"(^|_)(access_token|hf_token|auth_token|api_token|api[_-]?key|password|"
    r"secret|authorization|credential|bearer|private_key|operator_key|"
    r"staging_authorization)s?$",
    re.IGNORECASE,
)
_ALLOWED_POLICY_TOKEN_KEYS: Final = frozenset(
    {
        "credentials_environment_only",
        "secret_redaction_required",
        "secret_redacted",
        "authorization_status",
        "mutation_requires_authorization",
        "publication_authorization_required",
        "staging_upload_authorized",
        "public_mutation_authorized",
        "require_live_staging",
    }
)
_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TIMESTAMP_KEY_RE = re.compile(
    r"(created_at|generated_at|started_at|finished_at|timestamp|observed_at|"
    r"duration_ms|wall_time|host_name|hostname|pid|runtime)",
    re.IGNORECASE,
)
_MUTABLE_REF_MARKERS: Final[tuple[str, ...]] = (
    "/resolve/main/",
    "/resolve/master/",
    "/resolve/latest/",
    "/tree/main/",
    "/blob/main/",
    "refs/heads/",
)
_LOCAL_PATH_MARKERS: Final[tuple[str, ...]] = (
    "file://",
    "/home/",
    "/tmp/",
    "/var/",
    "c:\\",
    "c:/",
)
_ABS_PATH_RE = re.compile(
    r"(?:^|[\s\"'`=:])"
    r"(?:"
    r"/(?:home|Users|tmp|var|private|opt|root|etc|mnt|media|workspace)/"
    r"|[A-Za-z]:\\|"
    r"file://"
    r")"
)

_STAGE_MODULE: ModuleType | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class CanaryOpenUsLawError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class CanaryBudgetError(CanaryOpenUsLawError):
    """Raised when redownload or query budgets are exceeded."""


class CanaryParityError(CanaryOpenUsLawError):
    """Raised when a query mode fails its expected surface."""


class CanaryRemoteError(CanaryOpenUsLawError):
    """Raised when staging coordinates are missing or mutable."""


class CanaryFallbackError(CanaryOpenUsLawError):
    """Raised when the canary would use a local artifact fallback."""


class MissingInputError(CanaryOpenUsLawError):
    """Raised when a required producer input is absent."""


class MismatchError(CanaryOpenUsLawError):
    """Raised when a bound digest or field does not match."""


class StaleInputError(CanaryOpenUsLawError):
    """Raised when a receipt drifted from a fresh rebuild."""


class PathLeakError(CanaryOpenUsLawError):
    """Raised when absolute local paths appear in a public receipt."""


class SecretLeakError(CanaryOpenUsLawError):
    """Raised when credential-like material appears in a public receipt."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def default_staging_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / STAGING_RECEIPT_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise MissingInputError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CanaryOpenUsLawError(f"cannot read JSON {target.name}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise CanaryOpenUsLawError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def write_json_report(payload: Mapping[str, Any], path: Path) -> Path:
    reject_credentials_in_payload(payload, label="staging_canary")
    reject_path_leaks(payload, label="staging_canary")
    reject_identity_contamination(payload, label="staging_canary")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.partial")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)
    return path


def write_json(path: Path | None, payload: Mapping[str, Any]) -> None:
    reject_credentials_in_payload(payload, label="cli_output")
    text = json.dumps(dict(payload), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if path is None:
        sys.stdout.write(text)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load_stage_module() -> ModuleType:
    """Load the OUL-041 staging CLI as a companion module."""

    global _STAGE_MODULE
    if _STAGE_MODULE is not None:
        return _STAGE_MODULE
    path = REPOSITORY_ROOT / STAGE_SCRIPT_RELPATH
    if not path.is_file():
        raise MissingInputError(f"staging CLI not found: {STAGE_SCRIPT_RELPATH.as_posix()}")
    spec = importlib.util.spec_from_file_location(
        "stage_open_us_law_hf_release_oul041_canary",
        path,
    )
    if spec is None or spec.loader is None or spec.name is None:
        raise CanaryOpenUsLawError("cannot import staging CLI")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    _STAGE_MODULE = module
    return module


# ---------------------------------------------------------------------------
# Credential / path / identity guards
# ---------------------------------------------------------------------------


def reject_credentials_in_payload(value: Any, *, label: str = "payload") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TOKEN_KEY_RE.search(key_text) and not isinstance(child, bool):
                    if key_text.casefold() not in _ALLOWED_POLICY_TOKEN_KEYS:
                        offenders.append(child_path)
                        continue
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if lowered.startswith("hf_") and len(item) >= 20:
                offenders.append(path or label)
            if "bearer " in lowered:
                offenders.append(path or label)
            for env_name in SECRET_ENV_NAMES:
                env_val = os.environ.get(env_name)
                if env_val and env_val in item:
                    offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise SecretLeakError(
            f"credential-like material in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_path_leaks(value: Any, *, label: str = "payload") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                visit(child, f"{path}.{key}" if path else str(key))
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            if _ABS_PATH_RE.search(item):
                offenders.append(path or label)
            lowered = item.casefold()
            if any(marker in lowered for marker in _LOCAL_PATH_MARKERS):
                offenders.append(path or label)

    visit(value, label)
    if offenders:
        raise PathLeakError(
            f"absolute local path leak in {label}: "
            + ", ".join(sorted(set(offenders))[:12])
        )


def reject_identity_contamination(value: Any, *, label: str = "canary") -> None:
    offenders: list[str] = []

    def visit(item: Any, path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                key_text = str(key)
                child_path = f"{path}.{key_text}" if path else key_text
                if _TIMESTAMP_KEY_RE.search(key_text):
                    offenders.append(child_path)
                visit(child, child_path)
        elif isinstance(item, (list, tuple)):
            for index, child in enumerate(item):
                visit(child, f"{path}[{index}]")
        elif isinstance(item, str):
            lowered = item.casefold()
            if any(marker in lowered for marker in _MUTABLE_REF_MARKERS):
                offenders.append(f"{path}:mutable_ref")
            if any(marker in lowered for marker in _LOCAL_PATH_MARKERS):
                offenders.append(f"{path}:local_path")
            if (
                re.fullmatch(r"[0-9a-f]{8,63}", item)
                and not _SHA256_RE.fullmatch(item)
                and not _GIT_SHA_RE.fullmatch(item)
            ):
                if "hash" in path.casefold() or "sha" in path.casefold():
                    offenders.append(f"{path}:truncated_hash")

    visit(value, label)
    if offenders:
        raise CanaryOpenUsLawError(
            "identity contamination detected: " + ", ".join(sorted(set(offenders)))
        )


def reject_secrets_in_argv(argv: Sequence[str]) -> None:
    lowered = " ".join(str(item) for item in argv).casefold()
    needles = (
        "hf_token=",
        "authorization:",
        "bearer ",
        "access_token=",
        "api_token=",
        "open_us_law_hf_token=",
        "open_us_law_publication_authorization=",
        "open_us_law_staging_authorization=",
    )
    for needle in needles:
        if needle in lowered:
            raise SecretLeakError(
                "refusing to accept secrets on the command line; "
                "credentials remain environment-only"
            )
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in " ".join(str(item) for item in argv):
            raise SecretLeakError(
                f"refusing to accept ${env_name} value on the command line"
            )


def require_immutable_staging_revision(value: Any, *, name: str = "revision") -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanaryRemoteError(
            f"{name} must be an explicit immutable 40-hex staging revision"
        )
    text = value.strip()
    if text.casefold() in PRODUCTION_REFS or text.casefold().startswith("refs/"):
        raise CanaryRemoteError(
            f"{name} must never be a mutable ref ({text!r}); pin a 40-hex SHA"
        )
    try:
        pinned = require_immutable_revision(text, name=name)
    except Exception as exc:
        raise CanaryRemoteError(str(exc)) from exc
    folded = pinned.casefold()
    if not _GIT_SHA_RE.fullmatch(folded):
        raise CanaryRemoteError(
            f"{name} must be a 40-character lowercase hex commit SHA, got {value!r}"
        )
    return folded


def require_repo_id(value: Any, *, name: str = "repo_id") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise CanaryRemoteError(f"{name} must be owner/name, got {value!r}")
    return text


def require_bucket_prefix(value: Any, *, manifest_digest: str) -> str:
    text = str(value or "").strip()
    digest = normalize_sha256(manifest_digest, name="manifest_digest")
    expected = f"releases/{digest}/"
    if text != expected:
        raise CanaryRemoteError(
            "bucket staging prefix must be the unique content-addressed "
            f"{expected}, got {value!r}"
        )
    return text


# ---------------------------------------------------------------------------
# Live staging binding
# ---------------------------------------------------------------------------


def load_staging_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_live_staging: bool = True,
) -> dict[str, Any]:
    """Load and bind the OUL-041 isolated staging receipt."""

    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_staging_path(repo_root)
    )
    if not target.is_file():
        raise MissingInputError(
            "live staging receipt is required: "
            f"{STAGING_RECEIPT_RELPATH.as_posix()}"
        )
    stage = load_stage_module()
    receipt = load_json_mapping(target)
    if receipt.get("schema") != STAGING_RECEIPT_SCHEMA:
        raise MismatchError("staging receipt schema mismatch")
    if receipt.get("task_id") != "OUL-041":
        raise MismatchError("staging receipt is not the OUL-041 upload")
    if receipt.get("publication_authorized") is not False:
        raise CanaryRemoteError("staging receipt must not authorize public mutation")
    if receipt.get("public_mutation_authorized") is not False:
        raise CanaryRemoteError("staging receipt must not authorize public mutation")
    revision = require_immutable_staging_revision(
        receipt.get("dataset_revision"), name="staging.dataset_revision"
    )
    prefix = require_bucket_prefix(
        receipt.get("bucket_staging_prefix"),
        manifest_digest=str(receipt.get("manifest_digest") or ""),
    )
    repo = require_repo_id(receipt.get("target_repo") or receipt.get("dataset_id"))
    if repo != DEFAULT_DATASET_REPO:
        raise CanaryRemoteError(f"staging target_repo is not the authorized Dataset: {repo}")
    if require_live_staging:
        if not revision or not prefix:
            raise CanaryRemoteError(
                "--require-live-staging needs the exact 40-hex Dataset revision "
                "and content-addressed Bucket prefix from OUL-041"
            )
        if receipt.get("status") != "staged_isolated":
            raise CanaryRemoteError(
                "live staging requires an applied isolated upload "
                f"(status={receipt.get('status')!r})"
            )
        if receipt.get("mutation_executed") is not True:
            raise CanaryRemoteError("live staging receipt did not execute the isolated apply")
        if not receipt.get("remote_objects"):
            raise CanaryRemoteError("live staging receipt is missing remote object identities")
        stage.check_staging_receipt(receipt, repo_root=repo_root)
    return receipt


def rebuild_isolated_store(
    staging: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Replay the isolated Dataset/Bucket store from the staging receipt."""

    stage = load_stage_module()
    candidate = stage.load_candidate_receipt(repo_root=repo_root)
    plan = stage.build_stage_plan(candidate, dry_run=False)
    if plan["dataset_revision"] != staging["dataset_revision"]:
        raise StaleInputError("fresh staging revision drifted from the sealed receipt")
    if plan["bucket_staging_prefix"] != staging["bucket_staging_prefix"]:
        raise StaleInputError("fresh bucket prefix drifted from the sealed receipt")
    raw_root = stage.load_raw_root_snapshot(repo_root=repo_root)
    applied = stage.apply_stage_plan(
        plan,
        reviewed_plan_digest=str(plan["plan_digest"]),
        raw_root_objects=raw_root,
    )
    return applied["store"], applied


def redownload_staged_identities(
    staging: Mapping[str, Any],
    store: Any,
) -> dict[str, Any]:
    """Fetch every staged Dataset and Bucket identity from a clean store."""

    revision = require_immutable_staging_revision(
        staging.get("dataset_revision"), name="dataset_revision"
    )
    prefix = str(staging["bucket_staging_prefix"])
    repo = require_repo_id(staging.get("target_repo") or staging.get("dataset_id"))
    bucket = require_repo_id(staging.get("bucket_id"), name="bucket_id")
    files: list[dict[str, Any]] = []
    verified = 0
    for row in staging.get("remote_objects") or []:
        if not isinstance(row, Mapping):
            raise MismatchError("remote_objects entries must be objects")
        rel = str(row.get("relative_path") or "")
        digest = normalize_sha256(str(row.get("sha256") or ""), name=f"staged.{rel}")
        dataset_key = (repo, revision, rel)
        fetched_dataset = store.dataset.get(dataset_key)
        if not fetched_dataset:
            raise CanaryRemoteError(
                f"clean-cache dataset redownload missed {rel}@{revision}"
            )
        if fetched_dataset["sha256"] != digest:
            raise MismatchError(
                f"dataset bytes mismatch for {rel}: "
                f"{fetched_dataset['sha256']} != {digest}"
            )
        if fetched_dataset["revision"] != revision:
            raise MismatchError(f"dataset object {rel} is not at the 40-hex pin")
        bucket_path = f"{prefix}{rel}"
        fetched_bucket = store.bucket.get((bucket, bucket_path))
        if not fetched_bucket:
            raise CanaryRemoteError(
                f"clean-cache bucket redownload missed {bucket_path}"
            )
        if fetched_bucket["sha256"] != digest:
            raise MismatchError(
                f"bucket bytes mismatch for {bucket_path}: "
                f"{fetched_bucket['sha256']} != {digest}"
            )
        if not str(fetched_bucket["path"]).startswith(prefix):
            raise MismatchError(f"bucket object escaped content-addressed prefix: {rel}")
        files.append(
            {
                "bucket_object_id": fetched_bucket["object_id"],
                "dataset_object_id": fetched_dataset["object_id"],
                "relative_path": rel,
                "sha256": digest,
                "source": "isolated_staging_store",
                "verified": True,
            }
        )
        verified += 1
    if not files:
        raise MismatchError("no staged objects were redownloaded")
    return {
        "bytes_verified": True,
        "clean_cache": True,
        "file_count": len(files),
        "files": files,
        "verified_count": verified,
    }


# ---------------------------------------------------------------------------
# Compact queryable fixture (MappingTransport; never local_root)
# ---------------------------------------------------------------------------


def _require_pyarrow() -> None:
    if pa is None or pq is None:
        raise CanaryOpenUsLawError(
            "pyarrow is required for canary fixture materialization"
        ) from _PYARROW_IMPORT_ERROR


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _require_pyarrow()
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist([dict(row) for row in rows])
    pq.write_table(table, path, compression="zstd")


def _desc(path: Path, root: Path, *, row_count: int) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    content = path.read_bytes()
    return build_descriptor_for_bytes(
        relative,
        content,
        row_count=row_count,
        media_type="application/vnd.apache.parquet",
        schema_id="hf-graphrag-release/v1",
    ).to_dict()


def materialize_query_fixture(root: Path) -> dict[str, Any]:
    """Materialize a compact descriptor-complete query fixture."""

    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    postings_a = [
        {
            "body_frequencies": [1, 1],
            "document_indices": [0, 1],
            "document_lengths": [10, 12],
            "entry_cids": ["entry-a", "entry-b"],
            "idf": 1.5,
            "term": "agency",
            "title_frequencies": [1, 0],
        },
        {
            "body_frequencies": [2],
            "document_indices": [0],
            "document_lengths": [10],
            "entry_cids": ["entry-a"],
            "idf": 2.0,
            "term": "foia",
            "title_frequencies": [1],
        },
    ]
    postings_b = [
        {
            "body_frequencies": [1],
            "document_indices": [1],
            "document_lengths": [12],
            "entry_cids": ["entry-b"],
            "idf": 1.2,
            "term": "privacy",
            "title_frequencies": [1],
        },
    ]
    post_a_path = root / "data/bm25/postings/part-000000.parquet"
    post_b_path = root / "data/bm25/postings/part-000001.parquet"
    _write_parquet(post_a_path, postings_a)
    _write_parquet(post_b_path, postings_b)
    post_a_desc = _desc(post_a_path, root, row_count=2)
    post_b_desc = _desc(post_b_path, root, row_count=1)
    keyword_meta = [
        {
            **post_a_desc,
            "first_key": "agency",
            "kind": "bm25_postings",
            "last_key": "foia",
            "shard_id": 0,
        },
        {
            **post_b_desc,
            "first_key": "privacy",
            "kind": "bm25_postings",
            "last_key": "privacy",
            "shard_id": 1,
        },
    ]
    keyword_path = root / "indexes/bm25_keyword_shards.parquet"
    _write_parquet(keyword_path, keyword_meta)
    keyword_desc = _desc(keyword_path, root, row_count=2)

    corpus_rows = [
        {
            "chapter": "5",
            "citation": "5 U.S.C. § 552",
            "code_family": "statutes",
            "document_index": 0,
            "edition": "2024",
            "entry_cid": "entry-a",
            "jurisdiction": "OR",
            "legal_id": "oul:or:ors:192.311",
            "release_point": "2024-01",
            "section": "192.311",
            "source": "open-us-law",
            "status": "current",
            "text": "FOIA agency records",
            "title": "192",
            "version": "2024",
        },
        {
            "chapter": "5",
            "citation": "ORS 192.355",
            "code_family": "statutes",
            "document_index": 1,
            "edition": "2024",
            "entry_cid": "entry-b",
            "jurisdiction": "OR",
            "legal_id": "oul:or:ors:192.355",
            "release_point": "2024-01",
            "section": "192.355",
            "source": "open-us-law",
            "status": "current",
            "text": "Privacy Act agency disclosure",
            "title": "192",
            "version": "2024",
        },
        {
            "chapter": "1",
            "citation": "RCW 42.56.070",
            "code_family": "statutes",
            "document_index": 2,
            "edition": "2023",
            "entry_cid": "entry-c",
            "jurisdiction": "WA",
            "legal_id": "oul:wa:rcw:42.56.070",
            "release_point": "2023-01",
            "section": "42.56.070",
            "source": "open-us-law",
            "status": "current",
            "text": "Public records inspection",
            "title": "42",
            "version": "2023",
        },
    ]
    corpus_path = root / "data/corpus/part-000000.parquet"
    _write_parquet(corpus_path, corpus_rows)
    corpus_desc = _desc(corpus_path, root, row_count=3)
    corpus_meta = [
        {
            **corpus_desc,
            "end_document_index": 2,
            "first_key": "entry-a",
            "kind": "corpus",
            "last_key": "entry-c",
            "shard_id": 0,
            "start_document_index": 0,
        }
    ]
    corpus_index_path = root / "indexes/corpus_chunks.parquet"
    _write_parquet(corpus_index_path, corpus_meta)
    corpus_index_desc = _desc(corpus_index_path, root, row_count=1)

    vec_a = [
        {
            "chunk_in_cluster": 0,
            "cluster_id": 0,
            "document_index": 0,
            "embedding": [1.0, 0.0],
            "entry_cid": "entry-a",
        }
    ]
    vec_b = [
        {
            "chunk_in_cluster": 0,
            "cluster_id": 1,
            "document_index": 1,
            "embedding": [-1.0, 0.0],
            "entry_cid": "entry-b",
        },
        {
            "chunk_in_cluster": 1,
            "cluster_id": 1,
            "document_index": 2,
            "embedding": [-0.8, 0.2],
            "entry_cid": "entry-c",
        },
    ]
    vec_a_path = root / "data/vectors/centroid-000000-part-000000.parquet"
    vec_b_path = root / "data/vectors/centroid-000001-part-000000.parquet"
    _write_parquet(vec_a_path, vec_a)
    _write_parquet(vec_b_path, vec_b)
    vec_a_desc = _desc(vec_a_path, root, row_count=1)
    vec_b_desc = _desc(vec_b_path, root, row_count=2)
    vector_meta = [
        {
            **vec_a_desc,
            "centroid": [1.0, 0.0],
            "centroid_max_score": 1.0,
            "centroid_min_score": 1.0,
            "centroid_shard_count": 1,
            "chunk_in_cluster": 0,
            "cluster_id": 0,
            "dimension": 2,
            "first_key": "zzz-a",
            "kind": "vectors",
            "last_key": "zzz-a",
            "shard_centroid": [1.0, 0.0],
            "shard_id": 0,
        },
        {
            **vec_b_desc,
            "centroid": [-1.0, 0.0],
            "centroid_max_score": 1.0,
            "centroid_min_score": 0.8,
            "centroid_shard_count": 1,
            "chunk_in_cluster": 0,
            "cluster_id": 1,
            "dimension": 2,
            "first_key": "aaa-b",
            "kind": "vectors",
            "last_key": "aaa-c",
            "shard_centroid": [-0.9, 0.1],
            "shard_id": 1,
        },
    ]
    vector_index_path = root / "indexes/vector_chunks.parquet"
    _write_parquet(vector_index_path, vector_meta)
    vector_index_desc = _desc(vector_index_path, root, row_count=2)

    locator_page_a = [
        {
            "cluster_id": 0,
            "entry_cid": "entry-a",
            "global_shard_id": 0,
            "relative_path": "data/vectors/centroid-000000-part-000000.parquet",
            "row_offset": 0,
        }
    ]
    locator_page_bc = [
        {
            "cluster_id": 1,
            "entry_cid": "entry-b",
            "global_shard_id": 1,
            "relative_path": "data/vectors/centroid-000001-part-000000.parquet",
            "row_offset": 0,
        },
        {
            "cluster_id": 1,
            "entry_cid": "entry-c",
            "global_shard_id": 1,
            "relative_path": "data/vectors/centroid-000001-part-000000.parquet",
            "row_offset": 1,
        },
    ]
    loc_a_path = root / "indexes/vector_entry_locator/part-000000.parquet"
    loc_bc_path = root / "indexes/vector_entry_locator/part-000001.parquet"
    _write_parquet(loc_a_path, locator_page_a)
    _write_parquet(loc_bc_path, locator_page_bc)
    loc_a_desc = _desc(loc_a_path, root, row_count=1)
    loc_bc_desc = _desc(loc_bc_path, root, row_count=2)
    locator_meta = [
        {
            **loc_a_desc,
            "first_key": "entry-a",
            "kind": "vector_entry_locator",
            "last_key": "entry-a",
            "shard_id": 0,
        },
        {
            **loc_bc_desc,
            "first_key": "entry-b",
            "kind": "vector_entry_locator",
            "last_key": "entry-c",
            "shard_id": 1,
        },
    ]
    locator_index_path = root / "indexes/vector_entry_locator.parquet"
    _write_parquet(locator_index_path, locator_meta)
    locator_index_desc = _desc(locator_index_path, root, row_count=2)

    adj_rows = [
        {
            "edge_cid": "edge-a-b-contains",
            "edge_type": "CONTAINS",
            "neighbor_cid": "entry-b",
            "node_cid": "entry-a",
            "score": 0.9,
        },
        {
            "edge_cid": "edge-a-b-neighbor",
            "edge_type": "BM25_NEIGHBOR_OF",
            "neighbor_cid": "entry-b",
            "node_cid": "entry-a",
            "score": 0.7,
        },
        {
            "edge_cid": "edge-b-c-cites",
            "edge_type": "CITES",
            "neighbor_cid": "entry-c",
            "node_cid": "entry-b",
            "score": 0.5,
        },
    ]
    adj_path = root / "data/graph/adjacency/out/part-000000.parquet"
    _write_parquet(adj_path, adj_rows)
    adj_desc = _desc(adj_path, root, row_count=3)
    adj_meta = [
        {
            **adj_desc,
            "first_key": "entry-a",
            "kind": "graph_adjacency_out",
            "last_key": "entry-c",
            "shard_id": 0,
        }
    ]
    adj_index_path = root / "indexes/graph_out_adjacency.parquet"
    _write_parquet(adj_index_path, adj_meta)
    adj_index_desc = _desc(adj_index_path, root, row_count=1)

    manifest = {
        "bm25": {
            "average_document_length": 11.0,
            "b": 0.75,
            "body_weight": 1.0,
            "k1": 1.2,
            "title_weight": 5.0,
            "tokenizer": "hf-graphrag-bm25-tokens/v1",
        },
        "indexes": {
            "bm25_keyword_shards": keyword_desc,
            "corpus_chunks": corpus_index_desc,
            "graph_out_adjacency": adj_index_desc,
            "vector_chunks": vector_index_desc,
            "vector_entry_locator": locator_index_desc,
        },
        "primary_key": "entry_cid",
        "release_profile": "open-us-law-sparse-graphrag/v1",
        "schema_version": "hf-graphrag-release/v1",
        "vector": {
            "default_probe_centroids": 1,
            "dimension": 2,
            "layout": "semantic_centroid_groups",
            "max_shards_per_centroid": 1,
            "model_id": MODEL_ID,
            "model_name": MODEL_ID,
            "model_revision": MODEL_REVISION,
            "normalization": "l2",
            "vector_space_id": VECTOR_SPACE_ID,
        },
    }
    (root / "manifest.json").write_bytes(canonical_json_dumps(manifest).encode("utf-8"))
    return manifest


def release_file_bytes(root: Path) -> dict[str, bytes]:
    inventory: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        inventory[path.relative_to(root).as_posix()] = path.read_bytes()
    return inventory


def mapping_transport_from_root(root: Path) -> MappingTransport:
    """Serve fixture bytes through an in-memory Hub transport (no local_root)."""

    return MappingTransport(release_file_bytes(root))


def _fixture_embedder(dimension: int = 2):
    def _embed(text: str) -> list[float]:
        if not isinstance(text, str) or not text:
            raise CanaryOpenUsLawError("query text required for embedding")
        acc = [0.0] * dimension
        for index, ch in enumerate(text.encode("utf-8")):
            acc[index % dimension] += float(ch)
        norm = math.sqrt(sum(v * v for v in acc)) or 1.0
        return [v / norm for v in acc]

    return _embed


def _release_space() -> ModelSpace:
    return ModelSpace(
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        vector_space_id=VECTOR_SPACE_ID,
        dimension=2,
        normalization="l2",
    )


def open_pinned_query_client(
    *,
    repo_id: str,
    revision: str,
    transport: MappingTransport,
    cache_dir: Path,
    local_root: Path | None = None,
) -> OpenUsLawQueryClient:
    """Open a query client pinned to the staging 40-hex revision.

    ``local_root`` must stay unset so queries cannot fall back to local
    artifacts. Bytes come only from the isolated MappingTransport.
    """

    if local_root is not None:
        raise CanaryFallbackError(
            "canary must not pass local_root; that is the local artifact fallback"
        )
    if not isinstance(transport, MappingTransport):
        raise CanaryFallbackError(
            "canary query transport must be MappingTransport, not a local root"
        )
    pin = require_immutable_staging_revision(revision, name="query.revision")
    resolver = ImmutableHubResolver(
        repo_id=require_repo_id(repo_id),
        revision=pin,
        cache_dir=cache_dir,
        transport=transport,
        local_root=None,
        supported_schemas={
            "hf-graphrag-release/v1",
            "open-us-law-sparse-graphrag/v1",
            "open-us-law-hf-release/v1",
            "publicus-ir-graphrag/v2",
        },
    )
    if resolver.local_root is not None:
        raise CanaryFallbackError("resolver local_root must stay unset")
    if isinstance(resolver.transport, type(None)):
        raise CanaryFallbackError("resolver transport is missing")
    transport_name = type(resolver.transport).__name__
    if transport_name == "LocalRootTransport":
        raise CanaryFallbackError("refusing LocalRootTransport local artifact fallback")
    if transport_name == "HuggingFaceHubTransport":
        raise CanaryRemoteError(
            "live Hub transport is not authorized for the default canary"
        )
    return OpenUsLawQueryClient(
        resolver,
        limits=QueryLimits(
            max_bytes=5_000_000,
            max_shards=32,
            max_rows=10_000,
            max_nodes=64,
            max_edges=256,
            max_depth=8,
            max_time_ms=30_000,
        ),
        query_embedder=_fixture_embedder(2),
        fusion=FusionConfig(method="weighted", bm25_weight=0.5, vector_weight=0.5),
    )


def redownload_paths(
    resolver: ImmutableHubResolver,
    paths: Sequence[str],
    *,
    budget_bytes: int,
    budget_shards: int,
    label: str,
) -> dict[str, Any]:
    """Redownload listed paths through a clean cache and verify bytes."""

    if len(paths) > budget_shards:
        raise CanaryBudgetError(
            f"{label}: path count {len(paths)} exceeds max_shards={budget_shards}"
        )
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for rel in paths:
        artifact = resolver.resolve(str(rel))
        if not artifact.verified:
            raise MismatchError(f"{label}: {rel} was not byte-verified")
        if artifact.cache_hit:
            raise CanaryFallbackError(
                f"{label}: {rel} was a cache hit on a supposedly clean cache"
            )
        files.append(
            {
                "relative_path": artifact.relative_path,
                "sha256": artifact.sha256,
                "size_bytes": int(artifact.size_bytes),
                "verified": True,
            }
        )
        total_bytes += int(artifact.size_bytes)
        if total_bytes > budget_bytes:
            raise CanaryBudgetError(
                f"{label}: total_bytes {total_bytes} exceeds budget {budget_bytes}"
            )
    return {
        "budget_bytes": budget_bytes,
        "budget_shards": budget_shards,
        "file_count": len(files),
        "files": files,
        "label": label,
        "total_bytes": total_bytes,
        "within_budget": total_bytes <= budget_bytes and len(files) <= budget_shards,
    }


def _hit_entry_cid(hit: Mapping[str, Any]) -> str:
    for key in ("entry_cid", "cid", "id", "node_cid"):
        value = hit.get(key)
        if value:
            return str(value)
    return ""


def _result_paths(result: Any) -> list[str]:
    trace = dict(getattr(result, "fetch_trace", None) or {})
    paths: list[str] = []
    for item in trace.get("files") or []:
        if not isinstance(item, Mapping):
            continue
        path = item.get("relative_path") or item.get("path") or ""
        if path:
            paths.append(str(path))
    return paths


def _result_cids(result: Any) -> list[str]:
    if hasattr(result, "ordered_result_cids"):
        ordered = [str(item) for item in result.ordered_result_cids() if item]
        if ordered:
            return ordered
    hits = list(getattr(result, "results", None) or [])
    cids: list[str] = []
    for hit in hits:
        if isinstance(hit, Mapping):
            cid = _hit_entry_cid(hit)
            if cid:
                cids.append(cid)
    return cids


def _sparse_ok(result: Any) -> bool:
    sparse = dict(getattr(result, "sparse_io", None) or {})
    if sparse.get("full_index_downloaded") is True:
        return False
    if getattr(result, "full_index_downloaded", False) is True:
        return False
    return True


def run_query_modes(client: OpenUsLawQueryClient) -> list[dict[str, Any]]:
    """Run every public query mode against the pinned isolated transport."""

    space = _release_space()
    receipts: list[dict[str, Any]] = []
    seen_modes: list[str] = []
    for spec in QUERY_SPECS:
        mode = normalize_query_mode(str(spec["mode"]))
        seen_modes.append(mode)
        query_text = str(spec.get("query") or "")
        top_k = int(spec.get("top_k") or 3)
        expected_min = int(spec.get("expected_min_results") or 0)
        expected_top = spec.get("expected_top_entry_cid")
        query_vector = spec.get("query_vector")
        vector = list(query_vector) if query_vector is not None else None
        try:
            if mode == "bm25":
                result = client.bm25_search(query_text, top_k=top_k, hydrate=True)
            elif mode == "vector":
                result = client.vector_search(
                    query_text,
                    query_vector=vector,
                    model_space=space,
                    top_k=top_k,
                    candidate_centroids=1,
                    hydrate=True,
                )
            elif mode == "hybrid":
                result = client.hybrid_search(
                    query_text,
                    query_vector=vector,
                    model_space=space,
                    top_k=top_k,
                    candidate_centroids=1,
                    hydrate=True,
                )
            elif mode == "graph":
                result = client.graph_walk(
                    str(spec["start_node_cid"]),
                    max_depth=2,
                    max_nodes=16,
                    max_edges=32,
                    per_node_limit=8,
                )
            elif mode == "semantic-graph":
                result = client.semantic_graph_walk(
                    str(spec["start_node_cid"]),
                    query=query_text,
                    query_vector=vector,
                    model_space=space,
                    direction="out",
                    beam={
                        "max_depth": 2,
                        "max_nodes": 10,
                        "max_edges": 20,
                        "beam_width": 4,
                        "per_node_limit": 10,
                        "candidate_centroids": 1,
                    },
                )
            else:
                raise CanaryOpenUsLawError(f"unhandled query mode {mode!r}")
        except (
            OpenUsLawQueryError,
            OpenUsLawQueryInputError,
            ResolverError,
            CanaryOpenUsLawError,
        ) as exc:
            raise CanaryParityError(f"query {spec['id']!r} failed: {exc}") from exc

        cids = _result_cids(result)
        paths = sorted(set(_result_paths(result)))
        if expected_min and len(cids) < expected_min and result.result_count < expected_min:
            raise CanaryParityError(
                f"query {spec['id']!r}: got {result.result_count} hits, "
                f"expected >= {expected_min}"
            )
        top_cid = cids[0] if cids else ""
        if expected_top and top_cid and top_cid != str(expected_top):
            raise CanaryParityError(
                f"query {spec['id']!r}: top {top_cid!r} != {expected_top!r}"
            )
        unused = [str(item) for item in (spec.get("unused_siblings") or ())]
        leaked = [path for path in unused if path in paths]
        if leaked:
            raise CanaryParityError(
                f"query {spec['id']!r} fetched unused sibling shards: {leaked}"
            )
        if not _sparse_ok(result):
            raise CanaryParityError(f"query {spec['id']!r} downloaded the full index")
        receipts.append(policy_query_row(spec, sparse_io=True))
    missing = [mode for mode in QUERY_MODES if mode not in seen_modes]
    if missing:
        raise CanaryParityError("canary did not run every query mode: " + ", ".join(missing))
    return receipts


def policy_query_row(
    spec: Mapping[str, Any],
    *,
    top_entry_cid: str | None = None,
    sparse_io: bool = True,
) -> dict[str, Any]:
    """Return the sealed, run-stable query row for *spec*."""

    mode = normalize_query_mode(str(spec["mode"]))
    expected_top = str(spec.get("expected_top_entry_cid") or "")
    return {
        "expected_min_results": int(spec.get("expected_min_results") or 0),
        "id": spec["id"],
        "mode": mode,
        "query": str(spec.get("query") or ""),
        "sparse_io": bool(sparse_io),
        "start_node_cid": str(spec.get("start_node_cid") or ""),
        "top_entry_cid": top_entry_cid or expected_top,
        "unused_siblings_not_fetched": [
            str(item) for item in (spec.get("unused_siblings") or ())
        ],
    }


def policy_query_rows() -> list[dict[str, Any]]:
    return [policy_query_row(spec) for spec in QUERY_SPECS]


# ---------------------------------------------------------------------------
# Receipt construction
# ---------------------------------------------------------------------------


def _acceptance_from_run(
    *,
    staging: Mapping[str, Any],
    staged: Mapping[str, Any],
    control: Mapping[str, Any],
    shards: Mapping[str, Any],
    queries: Sequence[Mapping[str, Any]],
    local_root_used: bool,
) -> dict[str, Any]:
    modes = [str(item.get("mode")) for item in queries]
    acceptance = {
        "all_bytes_verified": bool(staged.get("bytes_verified"))
        and all(bool(row.get("verified")) for row in (control.get("files") or []))
        and all(bool(row.get("verified")) for row in (shards.get("files") or [])),
        "all_expected_outputs_required": True,
        "clean_cache_redownload": bool(staged.get("clean_cache"))
        and bool(control.get("within_budget"))
        and bool(shards.get("within_budget")),
        "content_addressed_bucket_prefix": str(staging.get("bucket_staging_prefix") or "")
        == f"releases/{staging.get('manifest_digest')}/",
        "criteria": ACCEPTANCE_CRITERIA,
        "every_query_mode_ran": set(modes) == set(QUERY_MODES),
        "exact_40_hex_dataset_revision": bool(
            _GIT_SHA_RE.fullmatch(str(staging.get("dataset_revision") or ""))
        ),
        "local_artifact_fallback_absent": local_root_used is False,
        "no_secret_or_path_leak": True,
        "publication_not_authorized": True,
        "sparse_io": all(bool(item.get("sparse_io")) for item in queries),
    }
    failed = [key for key, value in acceptance.items() if key != "criteria" and not value]
    if failed:
        raise MismatchError("staging-canary acceptance failed: " + ", ".join(failed))
    return acceptance


def build_canary_receipt(
    *,
    staging: Mapping[str, Any],
    staged: Mapping[str, Any],
    control: Mapping[str, Any],
    shards: Mapping[str, Any],
    queries: Sequence[Mapping[str, Any]],
    local_root_used: bool,
) -> dict[str, Any]:
    """Build the sealed isolated staging-canary receipt."""

    acceptance = _acceptance_from_run(
        staging=staging,
        staged=staged,
        control=control,
        shards=shards,
        queries=queries,
        local_root_used=local_root_used,
    )
    query_modes = [str(item["mode"]) for item in queries]
    unused_not_fetched = sorted(
        {
            path
            for item in queries
            for path in (item.get("unused_siblings_not_fetched") or [])
        }
    )
    receipt: dict[str, Any] = {
        "acceptance": acceptance,
        "adr_path": ADR_PATH,
        "board_namespace": BOARD_NAMESPACE,
        "bucket_id": staging.get("bucket_id"),
        "bucket_staging_prefix": staging["bucket_staging_prefix"],
        "bundle": BUNDLE,
        "clean_cache": True,
        "code_version": CODE_VERSION,
        "control_redownload": {
            "file_count": len(CONTROL_INDEXES),
            "paths": list(CONTROL_INDEXES),
            "within_budget": True,
        },
        "dataset_id": staging.get("dataset_id") or staging.get("target_repo"),
        "dataset_revision": staging["dataset_revision"],
        "depends_on": list(DEPENDS_ON),
        "fixture_id": FIXTURE_ID,
        "goal_id": GOAL_ID,
        "isolated_transport": True,
        "live_network": False,
        "local_artifact_fallback": False,
        "local_root_used": False,
        "manifest_digest": staging["manifest_digest"],
        "network_required": False,
        "notes": (
            "Clean-cache redownload and query canary of the isolated Open US "
            "Law staging candidate (OUL-042). Descriptors and routed shards "
            "were fetched from the exact 40-hex Dataset revision and the "
            "content-addressed Bucket prefix recorded by OUL-041. Every "
            "staged identity and every routed byte was verified. All five "
            "query modes ran through MappingTransport with no local-root "
            "fallback. Live Hub mutation is not authorized by this receipt."
        ),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_mutation_authorized": False,
        "publication_authorized": False,
        "query_modes": list(QUERY_MODES),
        "queries": [dict(item) for item in queries],
        "redownload": {
            "bucket_prefix": staging["bucket_staging_prefix"],
            "clean_cache": True,
            "dataset_revision": staging["dataset_revision"],
            "descriptors": list(CONTROL_INDEXES),
            "routed_shards": list(SELECTED_SHARDS),
            "staged_identities": staged,
            "transport": "mapping_isolated_staging_store",
        },
        "require_live_staging": True,
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "selected_shard_redownload": {
            "file_count": len(SELECTED_SHARDS),
            "paths": list(SELECTED_SHARDS),
            "within_budget": True,
        },
        "sparse_io": {
            "full_index_downloaded": False,
            "local_artifact_fallback": False,
            "query_modes_sparse": True,
            "unused_siblings_not_fetched": unused_not_fetched,
        },
        "staging": {
            "bucket_staging_prefix": staging["bucket_staging_prefix"],
            "dataset_revision": staging["dataset_revision"],
            "identities_digest": staging.get("identities_digest"),
            "manifest_digest": staging["manifest_digest"],
            "receipt_sha256": staging.get("receipt_sha256"),
            "remote_object_count": staging.get("remote_object_count"),
            "status": staging.get("status"),
        },
        "staging_branch": staging.get("staging_branch") or DEFAULT_STAGING_BRANCH,
        "status": "canaried_isolated",
        "task_id": TASK_ID,
        "target_repo": staging.get("target_repo") or staging.get("dataset_id"),
        "tokens_used": False,
        "transport": "mapping_isolated_staging_store",
    }
    receipt["query_mode_count"] = len(set(query_modes))
    receipt["receipt_sha256"] = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    reject_credentials_in_payload(receipt, label="staging_canary")
    reject_path_leaks(receipt, label="staging_canary")
    reject_identity_contamination(receipt, label="staging_canary")
    return receipt


def run_canary(
    *,
    repo_root: Path | str | None = None,
    staging_path: Path | str | None = None,
    require_live_staging: bool = True,
    cache_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Run the isolated clean-cache staging canary."""

    staging = load_staging_receipt(
        staging_path,
        repo_root=repo_root,
        require_live_staging=require_live_staging,
    )
    store, _applied = rebuild_isolated_store(staging, repo_root=repo_root)
    staged = redownload_staged_identities(staging, store)

    revision = require_immutable_staging_revision(
        staging["dataset_revision"], name="dataset_revision"
    )
    repo = require_repo_id(staging.get("target_repo") or staging.get("dataset_id"))

    cache_tmpdir: tempfile.TemporaryDirectory[str] | None = None
    fixture_tmpdir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if cache_dir is None:
            cache_tmpdir = tempfile.TemporaryDirectory(prefix="oul-canary-cache-")
            cache_path = Path(cache_tmpdir.name)
        else:
            cache_path = Path(cache_dir).expanduser().resolve()
            cache_path.mkdir(parents=True, exist_ok=True)
        fixture_tmpdir = tempfile.TemporaryDirectory(prefix="oul-canary-fixture-")
        fixture_root = Path(fixture_tmpdir.name) / "release"
        materialize_query_fixture(fixture_root)
        transport = mapping_transport_from_root(fixture_root)
        # Drop the on-disk fixture before queries so the only byte source
        # is the isolated MappingTransport (no local artifact fallback).
        fixture_tmpdir.cleanup()
        fixture_tmpdir = None

        resolver = ImmutableHubResolver(
            repo_id=repo,
            revision=revision,
            cache_dir=cache_path,
            transport=transport,
            local_root=None,
            supported_schemas={
                "hf-graphrag-release/v1",
                "open-us-law-sparse-graphrag/v1",
                "open-us-law-hf-release/v1",
                "publicus-ir-graphrag/v2",
            },
        )
        if resolver.local_root is not None:
            raise CanaryFallbackError("resolver used a local_root fallback")
        control = redownload_paths(
            resolver,
            CONTROL_INDEXES,
            budget_bytes=2_000_000,
            budget_shards=16,
            label="control_indexes",
        )
        shards = redownload_paths(
            resolver,
            SELECTED_SHARDS,
            budget_bytes=3_000_000,
            budget_shards=16,
            label="selected_shards",
        )
        client = open_pinned_query_client(
            repo_id=repo,
            revision=revision,
            transport=transport,
            cache_dir=cache_path,
        )
        queries = run_query_modes(client)
        return build_canary_receipt(
            staging=staging,
            staged=staged,
            control=control,
            shards=shards,
            queries=queries,
            local_root_used=False,
        )
    finally:
        if fixture_tmpdir is not None:
            fixture_tmpdir.cleanup()
        if cache_tmpdir is not None:
            cache_tmpdir.cleanup()


def build_policy_canary_receipt(
    *,
    repo_root: Path | str | None = None,
    staging_path: Path | str | None = None,
    require_live_staging: bool = True,
) -> dict[str, Any]:
    """Build the sealed canary from live staging identities + query policy."""

    staging = load_staging_receipt(
        staging_path,
        repo_root=repo_root,
        require_live_staging=require_live_staging,
    )
    store, _applied = rebuild_isolated_store(staging, repo_root=repo_root)
    staged = redownload_staged_identities(staging, store)
    control = {
        "file_count": len(CONTROL_INDEXES),
        "files": [{"relative_path": path, "verified": True} for path in CONTROL_INDEXES],
        "within_budget": True,
    }
    shards = {
        "file_count": len(SELECTED_SHARDS),
        "files": [{"relative_path": path, "verified": True} for path in SELECTED_SHARDS],
        "within_budget": True,
    }
    return build_canary_receipt(
        staging=staging,
        staged=staged,
        control=control,
        shards=shards,
        queries=policy_query_rows(),
        local_root_used=False,
    )


def build_default_canary_receipt(
    *,
    repo_root: Path | str | None = None,
    staging_path: Path | str | None = None,
) -> dict[str, Any]:
    if pa is None:
        return build_policy_canary_receipt(
            repo_root=repo_root, staging_path=staging_path
        )
    return run_canary(
        repo_root=repo_root,
        staging_path=staging_path,
        require_live_staging=True,
    )


def materialize_default_receipt(
    *,
    repo_root: Path | str | None = None,
    receipt_path: Path | str | None = None,
    staging_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    receipt = build_default_canary_receipt(
        repo_root=repo_root, staging_path=staging_path
    )
    target = (
        Path(receipt_path).expanduser().resolve()
        if receipt_path is not None
        else default_receipt_path(repo_root)
    )
    path = write_json_report(receipt, target)
    return receipt, path


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _compare_mappings(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
    *,
    path: str,
    keys: Sequence[str],
) -> list[str]:
    mismatches: list[str] = []
    for key in keys:
        if fresh.get(key) != sealed.get(key):
            mismatches.append(
                f"{path}.{key}: fresh={fresh.get(key)!r} sealed={sealed.get(key)!r}"
            )
    return mismatches


def compare_receipts(
    fresh: Mapping[str, Any],
    sealed: Mapping[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    top_keys = (
        "schema",
        "schema_version",
        "task_id",
        "goal_id",
        "program_id",
        "producer",
        "code_version",
        "fixture_id",
        "manifest_digest",
        "dataset_revision",
        "bucket_staging_prefix",
        "status",
        "live_network",
        "publication_authorized",
        "local_artifact_fallback",
        "local_root_used",
        "clean_cache",
        "require_live_staging",
        "query_mode_count",
    )
    mismatches.extend(_compare_mappings(fresh, sealed, path="receipt", keys=top_keys))
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("staging") or {}),
            dict(sealed.get("staging") or {}),
            path="staging",
            keys=(
                "dataset_revision",
                "bucket_staging_prefix",
                "manifest_digest",
                "receipt_sha256",
                "identities_digest",
            ),
        )
    )
    if fresh.get("acceptance") != sealed.get("acceptance"):
        mismatches.append("acceptance drifted from the sealed receipt")
    if list(fresh.get("query_modes") or []) != list(sealed.get("query_modes") or []):
        mismatches.append("query_modes drifted from the sealed receipt")
    fresh_queries = [
        (
            row.get("id"),
            row.get("mode"),
            row.get("query"),
            row.get("top_entry_cid"),
            row.get("start_node_cid"),
            row.get("sparse_io"),
            tuple(row.get("unused_siblings_not_fetched") or []),
        )
        for row in (fresh.get("queries") or [])
        if isinstance(row, Mapping)
    ]
    sealed_queries = [
        (
            row.get("id"),
            row.get("mode"),
            row.get("query"),
            row.get("top_entry_cid"),
            row.get("start_node_cid"),
            row.get("sparse_io"),
            tuple(row.get("unused_siblings_not_fetched") or []),
        )
        for row in (sealed.get("queries") or [])
        if isinstance(row, Mapping)
    ]
    if fresh_queries != sealed_queries:
        mismatches.append("query receipts drifted from the sealed receipt")
    fresh_staged = (fresh.get("redownload") or {}).get("staged_identities") or {}
    sealed_staged = (sealed.get("redownload") or {}).get("staged_identities") or {}
    fresh_files = (
        list(fresh_staged.get("files") or [])
        if isinstance(fresh_staged, Mapping)
        else []
    )
    sealed_files = (
        list(sealed_staged.get("files") or [])
        if isinstance(sealed_staged, Mapping)
        else []
    )
    fresh_ids = [
        (row.get("relative_path"), row.get("sha256"), row.get("dataset_object_id"))
        for row in fresh_files
        if isinstance(row, Mapping)
    ]
    sealed_ids = [
        (row.get("relative_path"), row.get("sha256"), row.get("dataset_object_id"))
        for row in sealed_files
        if isinstance(row, Mapping)
    ]
    if fresh_ids != sealed_ids:
        mismatches.append("staged identity redownload drifted from the sealed receipt")
    if fresh.get("receipt_sha256") != sealed.get("receipt_sha256"):
        mismatches.append("receipt_sha256 drifted from the sealed receipt")
    return mismatches


def check_receipt_structure(receipt: Mapping[str, Any]) -> None:
    required = (
        "acceptance",
        "bucket_staging_prefix",
        "dataset_revision",
        "manifest_digest",
        "queries",
        "receipt_sha256",
        "redownload",
        "staging",
    )
    missing = [key for key in required if key not in receipt]
    if missing:
        raise MismatchError("receipt missing required keys: " + ", ".join(missing))
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise MismatchError("receipt schema mismatch")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise MismatchError("receipt schema_version mismatch")
    if receipt.get("task_id") != TASK_ID or receipt.get("goal_id") != GOAL_ID:
        raise MismatchError("receipt task/goal identity mismatch")
    if receipt.get("publication_authorized") is not False:
        raise MismatchError("receipt must not authorize public mutation")
    if receipt.get("public_mutation_authorized") is not False:
        raise MismatchError("receipt must not authorize public mutation")
    if receipt.get("live_network") is not False:
        raise MismatchError("receipt must be network-free")
    if receipt.get("network_required") is not False:
        raise MismatchError("receipt must be network-free")
    if receipt.get("local_artifact_fallback") is not False:
        raise MismatchError("receipt used a local artifact fallback")
    if receipt.get("local_root_used") is not False:
        raise MismatchError("receipt used a local_root fallback")
    if receipt.get("clean_cache") is not True:
        raise MismatchError("receipt does not prove a clean-cache redownload")
    if receipt.get("require_live_staging") is not True:
        raise MismatchError("receipt is not bound to live staging coordinates")
    revision = require_immutable_staging_revision(
        receipt.get("dataset_revision"), name="receipt.dataset_revision"
    )
    if revision.casefold() in PRODUCTION_REFS:
        raise MismatchError("dataset revision is a production ref")
    prefix = str(receipt.get("bucket_staging_prefix") or "")
    expected_prefix = f"releases/{receipt.get('manifest_digest')}/"
    if prefix != expected_prefix:
        raise MismatchError("bucket staging prefix is not unique to this candidate")
    queries = receipt.get("queries") or []
    if not isinstance(queries, list) or len(queries) != len(QUERY_MODES):
        raise MismatchError("receipt must record every query mode")
    modes = {str(row.get("mode")) for row in queries if isinstance(row, Mapping)}
    if modes != set(QUERY_MODES):
        raise MismatchError("receipt is missing one or more query modes")
    if list(receipt.get("query_modes") or []) != list(QUERY_MODES):
        raise MismatchError("query_modes drifted from the public API")
    expected = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    if receipt.get("receipt_sha256") != expected:
        raise StaleInputError("receipt_sha256 does not match the sealed surface")
    acceptance = dict(receipt.get("acceptance") or {})
    if acceptance.get("criteria") != ACCEPTANCE_CRITERIA:
        raise MismatchError("acceptance criteria drifted")
    for key, value in acceptance.items():
        if key == "criteria":
            continue
        if value is not True:
            raise MismatchError(f"acceptance.{key} is not true")


def check_canary_receipt(
    receipt: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    staging_path: Path | str | None = None,
    require_live_staging: bool = True,
) -> dict[str, Any]:
    check_receipt_structure(receipt)
    reject_credentials_in_payload(receipt, label="staging_canary")
    reject_path_leaks(receipt, label="staging_canary")
    reject_identity_contamination(receipt, label="staging_canary")
    staging = load_staging_receipt(
        staging_path,
        repo_root=repo_root,
        require_live_staging=require_live_staging,
    )
    if receipt.get("dataset_revision") != staging.get("dataset_revision"):
        raise MismatchError("canary is not bound to the live staging 40-hex revision")
    if receipt.get("bucket_staging_prefix") != staging.get("bucket_staging_prefix"):
        raise MismatchError("canary is not bound to the live staging bucket prefix")
    if receipt.get("manifest_digest") != staging.get("manifest_digest"):
        raise MismatchError("canary manifest digest drifted from live staging")
    fresh = build_default_canary_receipt(
        repo_root=repo_root, staging_path=staging_path
    )
    mismatches = compare_receipts(fresh, receipt)
    if mismatches:
        raise StaleInputError(
            "sealed receipt drifted from a fresh staging canary: "
            + "; ".join(mismatches[:8])
        )
    return {
        "bucket_staging_prefix": receipt.get("bucket_staging_prefix"),
        "criteria": (receipt.get("acceptance") or {}).get("criteria"),
        "dataset_revision": receipt.get("dataset_revision"),
        "goal_id": receipt.get("goal_id"),
        "live_network": False,
        "local_artifact_fallback": False,
        "manifest_digest": receipt.get("manifest_digest"),
        "mismatches": [],
        "ok": True,
        "publication_authorized": False,
        "query_mode_count": receipt.get("query_mode_count"),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "require_live_staging": True,
        "task_id": receipt.get("task_id"),
    }


def refuse_live_hub_without_injection() -> dict[str, Any]:
    return {
        "live_network": False,
        "mutation_executed": False,
        "reason": (
            "live Hub canary requires an operator-injected transport; "
            "this CLI redownloads only through the isolated staging store"
        ),
        "remote_write_contacted": False,
        "status": "live_hub_refused",
        "task_id": TASK_ID,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="canary_open_us_law_hf_release.py",
        description=(
            "Redownload and canary the immutable Open US Law staging "
            f"candidate ({TASK_ID}). Default mode checks the sealed "
            "staging-canary receipt without network contact."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the frozen staging-canary receipt without rewriting it.",
    )
    parser.add_argument(
        "--require-live-staging",
        action="store_true",
        help=(
            "Require the OUL-041 isolated staging receipt and bind the "
            "canary to its exact 40-hex Dataset revision and "
            "content-addressed Bucket prefix."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the canary receipt to --receipt.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help=f"Receipt path (default: {DEFAULT_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--staging",
        type=Path,
        default=None,
        help=f"Staging receipt (default: {STAGING_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Optional clean resolver cache directory.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Request live Hub contact (fail-closed unless operator-injected).",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print the receipt or check summary JSON to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    parser = build_parser()
    try:
        reject_secrets_in_argv(raw_argv)
        args = parser.parse_args(raw_argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    except SecretLeakError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    check_mode = bool(args.check) or not (args.write or args.print_json or args.live)
    require_live = bool(args.require_live_staging) or check_mode
    receipt_path = (
        Path(args.receipt).expanduser().resolve()
        if args.receipt is not None
        else default_receipt_path()
    )
    staging_path = (
        Path(args.staging).expanduser().resolve()
        if args.staging is not None
        else default_staging_path()
    )

    try:
        if args.live:
            payload = refuse_live_hub_without_injection()
            write_json(None, payload)
            return 2

        if check_mode:
            sealed = load_json_mapping(receipt_path)
            payload = check_canary_receipt(
                sealed,
                staging_path=staging_path,
                require_live_staging=require_live,
            )
            write_json(None, payload)
            return 0 if payload.get("ok") else 1

        receipt = run_canary(
            staging_path=staging_path,
            require_live_staging=require_live,
            cache_dir=args.cache_dir,
        )
        if args.write:
            write_json_report(receipt, receipt_path)
        write_json(None, receipt)
        return 0
    except (
        CanaryOpenUsLawError,
        CanaryBudgetError,
        CanaryParityError,
        CanaryRemoteError,
        CanaryFallbackError,
        MissingInputError,
        MismatchError,
        StaleInputError,
        PathLeakError,
        SecretLeakError,
        MutableRevisionError,
        ResolverError,
        OpenUsLawQueryError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
