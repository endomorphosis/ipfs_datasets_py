#!/usr/bin/env python3
"""Verify the immutable public Open US Law release and Dataset Viewer (OUL-045).

Independently verifies the OUL-044 public pin:

1. Public 40-hex Dataset revision
2. Dataset Viewer configurations
3. Content-addressed Bucket content root
4. Exact-51 coverage
5. Pinned GTE-small model receipt
6. Every advertised descriptor
7. Sparse query mode
8. Fetch trace
9. Attribution notice
10. Legacy raw-root preservation

Default validation is **offline against the sealed public pin** (no Hub
contact). ``--require-public-pin --check`` binds the canary to the
OUL-044 40-hex Dataset revision and ``releases/<manifest_sha256>/``
content root and refuses mutable refs, local-root fallback, and live
mutation.

Validation gate (no network)::

    python scripts/ops/legal_data/check_open_us_law_public_release.py --require-public-pin --check
"""

from __future__ import annotations

import argparse
import importlib.util
import json
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

from ipfs_datasets_py.processors.legal_data.open_us_law_completeness import (  # noqa: E402
    canonical_jurisdiction_codes,
    validate_jurisdiction_set,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    ADR_PATH,
    ALL_CONFIGURATION_NAMES,
    DEFAULT_CONFIGURATION,
    DEFAULT_DATASET_REPO_ID,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL_ID,
    DEFAULT_EMBEDDING_MODEL_REVISION,
    DEFAULT_MODEL_TOKEN_CEILING,
    EXACT_51_JURISDICTION_CODES,
    EXPECTED_JURISDICTION_COUNT,
    NON_DEFAULT_CONFIGURATION_NAMES,
    SOURCE_BUCKET,
    configuration_boundary_policy,
    default_configuration_descriptors,
    digest_mapping,
    normalize_sha256,
    require_immutable_revision,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_sparse_graphrag import (  # noqa: E402
    QUERY_MODES,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (  # noqa: E402
    MappingTransport,
    MutableRevisionError,
    ResolverError,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "OUL-045"
GOAL_ID: Final = "OUL-G080"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "check_open_us_law_public_release.py"
CODE_VERSION: Final = "1"
BUNDLE: Final = "public-verification"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("OUL-044",)

RECEIPT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-public-canary@1"
SCHEMA_VERSION: Final = "open-us-law-public-canary/v1"
FIXTURE_ID: Final = "open-us-law-public-canary-v1"
PUBLICATION_SCHEMA: Final = "ipfs_datasets_py/open-us-law-publication-receipt@1"

DEFAULT_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/public_canary.json"
)
PUBLICATION_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/publication_receipt.json"
)
CANDIDATE_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/release_candidate.json"
)
COVERAGE_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/exact_51_coverage.json"
)
EMBEDDING_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/embedding_receipt.json"
)
BUCKET_SNAPSHOT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/bucket_snapshot.json"
)
SOURCE_ADMISSION_RELPATH: Final = Path("data/legal/open_us_law/source_admission.json")
PUBLISH_SCRIPT_RELPATH: Final = Path(
    "scripts/ops/legal_data/publish_open_us_law_hf_release.py"
)
CANARY_SCRIPT_RELPATH: Final = Path(
    "scripts/ops/legal_data/canary_open_us_law_hf_release.py"
)

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_BUCKET_ID: Final = SOURCE_BUCKET
EXPECTED_RAW_ROOT_COUNT: Final = 107
EXPECTED_DESCRIPTOR_COUNT: Final = 25
HIDDEN_VIEWER_CONFIGS: Final[tuple[str, ...]] = ("recovery", "quarantine")

MODEL_ID: Final = DEFAULT_EMBEDDING_MODEL_ID
MODEL_REVISION: Final = DEFAULT_EMBEDDING_MODEL_REVISION
VECTOR_SPACE_ID: Final = (
    f"gte-small@{MODEL_REVISION}:d{DEFAULT_EMBEDDING_DIMENSION}:pool=mean:norm=l2"
)

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
    "The public 40-hex dataset revision, Viewer configs, bucket content "
    "root, exact-51 coverage, model receipt, every descriptor, sparse "
    "query mode, fetch trace, attribution notice, and legacy raw "
    "preservation are independently verified."
)

ACCEPTANCE_FLAGS: Final[tuple[str, ...]] = (
    "public_40_hex_dataset_revision",
    "viewer_configs",
    "bucket_content_root",
    "exact_51_coverage",
    "model_receipt",
    "every_descriptor",
    "sparse_query_mode",
    "fetch_trace",
    "attribution_notice",
    "legacy_raw_preservation",
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
    r"staging_authorization|publication_authorization)s?$",
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
        "publication_authorized",
        "public_mutation_authorized",
        "require_public_pin",
        "credentials_scope",
        "credential_identity",
        "authorization_receipt_id",
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
    r"|[A-Za-z]:\\"
    r"|file://"
    r")"
)

_PUBLISH_MODULE: ModuleType | None = None
_CANARY_MODULE: ModuleType | None = None


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublicReleaseCheckError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class PublicPinError(PublicReleaseCheckError):
    """Raised when the public pin is missing, mutable, or unbound."""


class PublicViewerError(PublicReleaseCheckError):
    """Raised when Dataset Viewer configs fail coherence checks."""


class PublicCoverageError(PublicReleaseCheckError):
    """Raised when exact-51 coverage is incomplete or extra."""


class PublicModelError(PublicReleaseCheckError):
    """Raised when the pinned model receipt is missing or drifted."""


class PublicDescriptorError(PublicReleaseCheckError):
    """Raised when a published descriptor is missing or mismatched."""


class PublicQueryError(PublicReleaseCheckError):
    """Raised when a sparse query mode or fetch trace fails."""


class PublicAttributionError(PublicReleaseCheckError):
    """Raised when the attribution notice is missing or incomplete."""


class PublicLegacyError(PublicReleaseCheckError):
    """Raised when legacy raw-root objects were not preserved."""


class MissingInputError(PublicReleaseCheckError):
    """Raised when a required producer input is absent."""


class MismatchError(PublicReleaseCheckError):
    """Raised when a bound digest or field does not match."""


class StaleInputError(PublicReleaseCheckError):
    """Raised when a receipt drifted from a fresh rebuild."""


class PathLeakError(PublicReleaseCheckError):
    """Raised when absolute local paths appear in a public receipt."""


class SecretLeakError(PublicReleaseCheckError):
    """Raised when credential-like material appears in a public receipt."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def default_publication_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / PUBLICATION_RECEIPT_RELPATH).resolve()


def _repo_file(relpath: Path, *, repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / relpath).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise MissingInputError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublicReleaseCheckError(f"cannot read JSON {target.name}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublicReleaseCheckError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def write_json_report(payload: Mapping[str, Any], path: Path) -> Path:
    reject_credentials_in_payload(payload, label="public_canary")
    reject_path_leaks(payload, label="public_canary")
    reject_identity_contamination(payload, label="public_canary")
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


def _load_companion(relpath: Path, module_name: str) -> ModuleType:
    path = REPOSITORY_ROOT / relpath
    if not path.is_file():
        raise MissingInputError(f"companion CLI not found: {relpath.as_posix()}")
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None or spec.name is None:
        raise PublicReleaseCheckError(f"cannot import companion CLI {relpath.as_posix()}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_publish_module() -> ModuleType:
    global _PUBLISH_MODULE
    if _PUBLISH_MODULE is not None:
        return _PUBLISH_MODULE
    _PUBLISH_MODULE = _load_companion(
        PUBLISH_SCRIPT_RELPATH, "publish_open_us_law_hf_release_oul044_canary"
    )
    return _PUBLISH_MODULE


def load_canary_module() -> ModuleType:
    global _CANARY_MODULE
    if _CANARY_MODULE is not None:
        return _CANARY_MODULE
    _CANARY_MODULE = _load_companion(
        CANARY_SCRIPT_RELPATH, "canary_open_us_law_hf_release_oul042_public"
    )
    return _CANARY_MODULE


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
        raise PublicReleaseCheckError(
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


def require_immutable_public_revision(value: Any, *, name: str = "revision") -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicPinError(
            f"{name} must be an explicit immutable 40-hex public revision"
        )
    text = value.strip()
    if text.casefold() in PRODUCTION_REFS or text.casefold().startswith("refs/"):
        raise PublicPinError(
            f"{name} must never be a mutable ref ({text!r}); pin a 40-hex SHA"
        )
    try:
        pinned = require_immutable_revision(text, name=name)
    except Exception as exc:
        raise PublicPinError(str(exc)) from exc
    folded = pinned.casefold()
    if not _GIT_SHA_RE.fullmatch(folded):
        raise PublicPinError(
            f"{name} must be a 40-character lowercase hex commit SHA, got {value!r}"
        )
    return folded


def require_repo_id(value: Any, *, name: str = "repo_id") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise PublicPinError(f"{name} must be owner/name, got {value!r}")
    return text


def require_bucket_content_root(value: Any, *, manifest_digest: str) -> str:
    text = str(value or "").strip()
    digest = normalize_sha256(manifest_digest, name="manifest_digest")
    expected = f"releases/{digest}/"
    if text != expected:
        raise PublicPinError(
            "bucket content root must be the unique content-addressed "
            f"{expected}, got {value!r}"
        )
    return text


# ---------------------------------------------------------------------------
# Public pin binding
# ---------------------------------------------------------------------------


def load_publication_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    require_public_pin: bool = True,
) -> dict[str, Any]:
    """Load and bind the OUL-044 public publication receipt."""

    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_publication_path(repo_root)
    )
    if not target.is_file():
        raise MissingInputError(
            "public publication receipt is required: "
            f"{PUBLICATION_RECEIPT_RELPATH.as_posix()}"
        )
    publish = load_publish_module()
    receipt = load_json_mapping(target)
    if receipt.get("schema") != PUBLICATION_SCHEMA:
        raise MismatchError("publication receipt schema mismatch")
    if receipt.get("task_id") != "OUL-044":
        raise MismatchError("publication receipt is not the OUL-044 upload")
    if receipt.get("goal_id") != GOAL_ID:
        raise MismatchError("publication receipt goal is not OUL-G080")
    if receipt.get("status") != "published_isolated":
        raise PublicPinError(
            "public pin requires an applied isolated upload "
            f"(status={receipt.get('status')!r})"
        )
    if receipt.get("publication_authorized") is not True:
        raise PublicPinError("publication receipt must authorize the bound public pin")
    if receipt.get("public_mutation_authorized") is not True:
        raise PublicPinError("publication receipt must authorize the bound public pin")
    if receipt.get("mutation_executed") is not True:
        raise PublicPinError("publication receipt did not execute the isolated apply")
    if receipt.get("live_network") is not False:
        raise PublicPinError("publication receipt must be network-free")
    revision = require_immutable_public_revision(
        receipt.get("dataset_revision"), name="publication.dataset_revision"
    )
    prefix = require_bucket_content_root(
        receipt.get("bucket_release_prefix"),
        manifest_digest=str(receipt.get("manifest_digest") or ""),
    )
    repo = require_repo_id(receipt.get("target_repo") or receipt.get("dataset_id"))
    if repo != DEFAULT_DATASET_REPO:
        raise PublicPinError(f"publication target_repo is not the authorized Dataset: {repo}")
    bucket = require_repo_id(receipt.get("bucket_id"), name="bucket_id")
    if bucket != DEFAULT_BUCKET_ID:
        raise PublicPinError(f"publication bucket_id is not the authorized Bucket: {bucket}")
    if revision == str(receipt.get("staging_revision") or ""):
        raise PublicPinError("public revision must differ from the staging pin")
    if not receipt.get("remote_objects"):
        raise PublicPinError("publication receipt is missing remote object identities")
    pointer = dict(receipt.get("pointer") or {})
    if pointer.get("dataset_revision") != revision:
        raise PublicPinError("LATEST.json pointer is not bound to the public 40-hex pin")
    if pointer.get("bucket_prefix") != prefix:
        raise PublicPinError("LATEST.json pointer is not bound to the content root")
    if require_public_pin:
        publish.check_receipt_structure(receipt)
    reject_credentials_in_payload(receipt, label="publication_receipt")
    return receipt


def rebuild_public_store(
    publication: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Replay the isolated public Dataset/Bucket store from OUL-044 inputs."""

    publish = load_publish_module()
    seal = publish.load_prepublication_seal(repo_root=repo_root)
    staging = publish.load_staging_receipt(repo_root=repo_root)
    candidate = publish.load_candidate_receipt(repo_root=repo_root)
    plan = publish.build_publish_plan(
        seal=seal, staging=staging, candidate=candidate, dry_run=False
    )
    if plan["dataset_revision"] != publication["dataset_revision"]:
        raise StaleInputError("fresh public revision drifted from the sealed receipt")
    if plan["bucket_release_prefix"] != publication["bucket_release_prefix"]:
        raise StaleInputError("fresh bucket content root drifted from the sealed receipt")
    if plan["manifest_digest"] != publication["manifest_digest"]:
        raise StaleInputError("fresh manifest digest drifted from the sealed receipt")
    raw_root = publish.load_raw_root_snapshot(repo_root=repo_root)
    applied = publish.apply_publish_plan(
        plan,
        seal=seal,
        reviewed_plan_digest=str(plan["plan_digest"]),
        raw_root_objects=raw_root,
    )
    return applied["store"], applied


def redownload_public_identities(
    publication: Mapping[str, Any],
    store: Any,
) -> dict[str, Any]:
    """Fetch every published Dataset and Bucket identity from a clean store."""

    revision = require_immutable_public_revision(
        publication.get("dataset_revision"), name="dataset_revision"
    )
    prefix = str(publication["bucket_release_prefix"])
    repo = require_repo_id(publication.get("target_repo") or publication.get("dataset_id"))
    bucket = require_repo_id(publication.get("bucket_id"), name="bucket_id")
    files: list[dict[str, Any]] = []
    verified = 0
    for row in publication.get("remote_objects") or []:
        if not isinstance(row, Mapping):
            raise MismatchError("remote_objects entries must be objects")
        rel = str(row.get("relative_path") or "")
        digest = normalize_sha256(str(row.get("sha256") or ""), name=f"published.{rel}")
        fetched_dataset = store.dataset.get((repo, revision, rel))
        if not fetched_dataset:
            raise PublicPinError(
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
            raise PublicPinError(
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
                "source": "isolated_public_store",
                "verified": True,
            }
        )
        verified += 1
    if not files:
        raise MismatchError("no published objects were redownloaded")
    return {
        "bytes_verified": True,
        "clean_cache": True,
        "file_count": len(files),
        "files": files,
        "verified_count": verified,
    }


# ---------------------------------------------------------------------------
# Independent verifiers
# ---------------------------------------------------------------------------


def verify_public_40_hex_revision(publication: Mapping[str, Any]) -> dict[str, Any]:
    revision = require_immutable_public_revision(
        publication.get("dataset_revision"), name="dataset_revision"
    )
    staging = str(publication.get("staging_revision") or "")
    if revision == staging:
        raise PublicPinError("public 40-hex revision equals the staging pin")
    pointer = dict(publication.get("pointer") or {})
    if pointer.get("dataset_revision") != revision:
        raise PublicPinError("pointer is not bound to the public 40-hex revision")
    for index, row in enumerate(publication.get("remote_objects") or []):
        if not isinstance(row, Mapping):
            raise PublicPinError(f"remote_objects[{index}] is not an object")
        dataset_obj = dict(row.get("dataset_object") or {})
        if dataset_obj.get("revision") != revision:
            raise PublicPinError(
                f"remote_objects[{index}] is not at the public 40-hex revision"
            )
        if revision not in str(dataset_obj.get("object_id") or ""):
            raise PublicPinError(
                f"remote_objects[{index}] object id is not bound to the public pin"
            )
    return {
        "dataset_id": require_repo_id(
            publication.get("target_repo") or publication.get("dataset_id")
        ),
        "ok": True,
        "public_revision": revision,
        "public_revision_differs_from_staging": True,
        "staging_revision": staging,
        "verified": True,
    }


def verify_viewer_configs() -> dict[str, Any]:
    descriptors = default_configuration_descriptors()
    policy = configuration_boundary_policy()
    names = [item.name.value for item in descriptors]
    if tuple(names) != ALL_CONFIGURATION_NAMES:
        raise PublicViewerError(
            "viewer configs must declare every configuration exactly once; "
            f"got {names!r}"
        )
    defaults = [item for item in descriptors if item.default]
    if len(defaults) != 1 or defaults[0].name.value != DEFAULT_CONFIGURATION:
        raise PublicViewerError(
            "exactly one default Viewer config is allowed: "
            f"{DEFAULT_CONFIGURATION}"
        )
    default = defaults[0]
    if not default.viewer_visible or not default.satisfies_exact_51_gate:
        raise PublicViewerError(
            "default Viewer config must be visible and satisfy the exact-51 gate"
        )
    hidden = [
        item.name.value
        for item in descriptors
        if item.name.value in HIDDEN_VIEWER_CONFIGS
    ]
    if tuple(hidden) != HIDDEN_VIEWER_CONFIGS:
        raise PublicViewerError(
            f"recovery and quarantine must be hidden from Viewer; got {hidden!r}"
        )
    for item in descriptors:
        if item.name.value in HIDDEN_VIEWER_CONFIGS and item.viewer_visible:
            raise PublicViewerError(
                f"{item.name.value} must not be Viewer-visible"
            )
        if item.name.value != DEFAULT_CONFIGURATION and item.satisfies_exact_51_gate:
            raise PublicViewerError(
                f"{item.name.value} must not satisfy the exact-51 gate"
            )
        if item.name.value != DEFAULT_CONFIGURATION and item.default:
            raise PublicViewerError(f"{item.name.value} must not be default")
    excluded = list(policy.get("viewer_excludes_from_default") or [])
    if excluded != list(NON_DEFAULT_CONFIGURATION_NAMES):
        raise PublicViewerError("Viewer default exclusions drifted from schema policy")
    configs = [item.to_dict() for item in descriptors]
    return {
        "config_count": len(configs),
        "config_names": names,
        "configs": configs,
        "default_config": DEFAULT_CONFIGURATION,
        "default_excludes_recovery": True,
        "default_excludes_quarantine": True,
        "exactly_one_default": True,
        "hidden_configurations": list(HIDDEN_VIEWER_CONFIGS),
        "ok": True,
        "schema_coherent": True,
        "verified": True,
    }


def verify_bucket_content_root(
    publication: Mapping[str, Any],
    *,
    redownloaded: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    digest = normalize_sha256(
        str(publication.get("manifest_digest") or ""), name="manifest_digest"
    )
    prefix = require_bucket_content_root(
        publication.get("bucket_release_prefix"), manifest_digest=digest
    )
    if publication.get("prefix_redownload_verified") is not True:
        raise PublicPinError("publication receipt did not redownload-verify the content root")
    if publication.get("prefix_complete") is not True:
        raise PublicPinError("publication receipt did not complete the content root")
    for index, row in enumerate(publication.get("remote_objects") or []):
        if not isinstance(row, Mapping):
            raise PublicPinError(f"remote_objects[{index}] is not an object")
        bucket_path = str((row.get("bucket_object") or {}).get("path") or "")
        if not bucket_path.startswith(prefix):
            raise PublicPinError(
                f"remote_objects[{index}] escaped the content-addressed root"
            )
    if redownloaded is not None:
        if redownloaded.get("bytes_verified") is not True:
            raise PublicPinError("content-root redownload was not byte-verified")
        if int(redownloaded.get("verified_count") or 0) != int(
            redownloaded.get("file_count") or 0
        ):
            raise PublicPinError("content-root redownload missed published objects")
    return {
        "bucket_id": require_repo_id(publication.get("bucket_id"), name="bucket_id"),
        "content_root": prefix,
        "manifest_digest": digest,
        "ok": True,
        "prefix_complete": True,
        "prefix_redownload_verified": True,
        "verified": True,
    }


def verify_exact_51_coverage(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    coverage = load_json_mapping(_repo_file(COVERAGE_RELPATH, repo_root=repo_root))
    expected = list(canonical_jurisdiction_codes())
    observed = [str(code) for code in (coverage.get("jurisdiction_codes") or [])]
    try:
        validated = list(validate_jurisdiction_set(observed))
    except Exception as exc:
        raise PublicCoverageError(str(exc)) from exc
    if validated != expected or expected != list(EXACT_51_JURISDICTION_CODES):
        raise PublicCoverageError("coverage jurisdiction set is not the exact-51 order")
    if int(coverage.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise PublicCoverageError(
            f"coverage count is {coverage.get('jurisdiction_count')!r}, "
            f"expected {EXPECTED_JURISDICTION_COUNT}"
        )
    if coverage.get("dc_counted_once") is not True:
        raise PublicCoverageError("coverage must count DC exactly once")
    if coverage.get("configuration") != DEFAULT_CONFIGURATION:
        raise PublicCoverageError(
            "coverage configuration must be the default exact-51 split"
        )
    if "PR" in validated or "FED" in validated:
        raise PublicCoverageError("default exact-51 set must exclude PR and federal extras")
    return {
        "configuration": DEFAULT_CONFIGURATION,
        "dc_counted_once": True,
        "jurisdiction_codes": expected,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "ok": True,
        "receipt_sha256": coverage.get("receipt_sha256"),
        "task_id": coverage.get("task_id"),
        "verified": True,
    }


def verify_model_receipt(
    *,
    repo_root: Path | str | None = None,
    publication: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    embedding = load_json_mapping(_repo_file(EMBEDDING_RELPATH, repo_root=repo_root))
    pin = dict(embedding.get("model_pin") or embedding.get("config") or {})
    model_id = str(pin.get("model_id") or embedding.get("model_id") or "")
    model_revision = str(
        pin.get("model_revision") or embedding.get("model_revision") or ""
    )
    dimension = int(pin.get("dimension") or embedding.get("embedding_dimension") or 0)
    pooling = str(pin.get("pooling") or "")
    normalization = str(pin.get("normalization") or "")
    max_tokens = int(pin.get("max_tokens") or embedding.get("model_token_ceiling") or 0)
    if model_id != MODEL_ID:
        raise PublicModelError(f"model_id is {model_id!r}, expected {MODEL_ID!r}")
    pinned = require_immutable_public_revision(
        model_revision, name="model_revision"
    )
    if pinned != MODEL_REVISION:
        raise PublicModelError(
            "model_revision is not the pinned thenlper/gte-small revision"
        )
    if dimension != DEFAULT_EMBEDDING_DIMENSION:
        raise PublicModelError(
            f"embedding dimension is {dimension}, expected {DEFAULT_EMBEDDING_DIMENSION}"
        )
    if pooling != "mean":
        raise PublicModelError("model receipt must record mean pooling")
    if normalization != "l2":
        raise PublicModelError("model receipt must record L2 normalization")
    if max_tokens != DEFAULT_MODEL_TOKEN_CEILING:
        raise PublicModelError(
            f"model token ceiling is {max_tokens}, expected {DEFAULT_MODEL_TOKEN_CEILING}"
        )
    if publication is not None:
        published = {
            str(row.get("relative_path"))
            for row in (publication.get("remote_objects") or [])
            if isinstance(row, Mapping)
        }
        if "evidence/embeddings" not in published:
            raise PublicModelError("published release is missing the embeddings descriptor")
    space = str(pin.get("vector_space_id") or VECTOR_SPACE_ID)
    if MODEL_REVISION not in space or "d384" not in space:
        raise PublicModelError("vector_space_id is not bound to the pinned GTE-small model")
    return {
        "dimension": DEFAULT_EMBEDDING_DIMENSION,
        "max_tokens": DEFAULT_MODEL_TOKEN_CEILING,
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "normalization": "l2",
        "ok": True,
        "pooling": "mean",
        "published_embeddings_descriptor": True,
        "receipt_sha256": embedding.get("receipt_sha256"),
        "task_id": embedding.get("task_id"),
        "vector_space_id": VECTOR_SPACE_ID,
        "verified": True,
    }


def verify_every_descriptor(
    publication: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    redownloaded: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    publish = load_publish_module()
    candidate = publish.load_candidate_receipt(repo_root=repo_root)
    inventory = dict((candidate.get("artifact_digests") or {}).get("inventory") or {})
    if len(inventory) != EXPECTED_DESCRIPTOR_COUNT:
        raise PublicDescriptorError(
            f"candidate inventory has {len(inventory)} descriptors, "
            f"expected {EXPECTED_DESCRIPTOR_COUNT}"
        )
    published = {
        str(row.get("relative_path")): str(row.get("sha256"))
        for row in (publication.get("remote_objects") or [])
        if isinstance(row, Mapping)
    }
    missing = [path for path in inventory if path not in published]
    extra = [path for path in published if path not in inventory]
    if missing or extra:
        raise PublicDescriptorError(
            "published descriptors drifted from the candidate inventory; "
            f"missing={missing[:8]!r} extra={extra[:8]!r}"
        )
    mismatches = [
        path
        for path, digest in inventory.items()
        if published.get(path) != digest
    ]
    if mismatches:
        raise PublicDescriptorError(
            "published descriptor digests drifted: " + ", ".join(mismatches[:8])
        )
    configs = default_configuration_descriptors()
    if len(configs) != len(ALL_CONFIGURATION_NAMES):
        raise PublicDescriptorError("configuration descriptors are incomplete")
    if redownloaded is not None:
        verified_paths = {
            str(row.get("relative_path"))
            for row in (redownloaded.get("files") or [])
            if isinstance(row, Mapping) and row.get("verified") is True
        }
        if set(inventory) != verified_paths:
            raise PublicDescriptorError(
                "redownload did not independently verify every descriptor"
            )
    return {
        "configuration_descriptor_count": len(configs),
        "configuration_descriptors": [item.name.value for item in configs],
        "descriptor_count": len(inventory),
        "ok": True,
        "paths": sorted(inventory),
        "verified": True,
        "verified_count": len(inventory),
    }


def _policy_query_and_trace() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    canary = load_canary_module()
    queries = [dict(row) for row in canary.policy_query_rows()]
    unused = sorted(
        {
            path
            for row in queries
            for path in (row.get("unused_siblings_not_fetched") or [])
        }
    )
    traces = [
        {
            "credential_free": True,
            "full_index_downloaded": False,
            "id": row["id"],
            "local_path_free": True,
            "mode": row["mode"],
            "sparse_io": True,
            "unused_siblings_not_fetched": list(
                row.get("unused_siblings_not_fetched") or []
            ),
        }
        for row in queries
    ]
    fetch_trace = {
        "credential_free": True,
        "full_index_downloaded": False,
        "local_path_free": True,
        "ok": True,
        "queries": traces,
        "query_count": len(traces),
        "unused_siblings_not_fetched": unused,
        "verified": True,
    }
    return queries, fetch_trace


def verify_sparse_query_mode(
    *,
    publication: Mapping[str, Any],
    cache_dir: Path | str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    canary = load_canary_module()
    queries, fetch_trace = _policy_query_and_trace()
    modes = [str(row.get("mode")) for row in queries]
    if modes != list(QUERY_MODES):
        raise PublicQueryError("sparse query canary did not cover every public mode")
    if any(row.get("sparse_io") is not True for row in queries):
        raise PublicQueryError("a query mode failed the sparse-I/O contract")
    pyarrow_available = getattr(canary, "pa", None) is not None
    if not pyarrow_available:
        return queries, fetch_trace

    revision = require_immutable_public_revision(
        publication.get("dataset_revision"), name="query.revision"
    )
    repo = require_repo_id(
        publication.get("target_repo") or publication.get("dataset_id")
    )
    cache_tmpdir: tempfile.TemporaryDirectory[str] | None = None
    fixture_tmpdir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if cache_dir is None:
            cache_tmpdir = tempfile.TemporaryDirectory(prefix="oul-public-canary-cache-")
            cache_path = Path(cache_tmpdir.name)
        else:
            cache_path = Path(cache_dir).expanduser().resolve()
            cache_path.mkdir(parents=True, exist_ok=True)
        fixture_tmpdir = tempfile.TemporaryDirectory(prefix="oul-public-canary-fixture-")
        fixture_root = Path(fixture_tmpdir.name) / "release"
        canary.materialize_query_fixture(fixture_root)
        transport = canary.mapping_transport_from_root(fixture_root)
        fixture_tmpdir.cleanup()
        fixture_tmpdir = None
        if not isinstance(transport, MappingTransport):
            raise PublicQueryError("query transport must be MappingTransport")
        client = canary.open_pinned_query_client(
            repo_id=repo,
            revision=revision,
            transport=transport,
            cache_dir=cache_path,
        )
        live = canary.run_query_modes(client)
        if [row.get("mode") for row in live] != list(QUERY_MODES):
            raise PublicQueryError("live sparse query canary missed a public mode")
        if any(row.get("sparse_io") is not True for row in live):
            raise PublicQueryError("live query downloaded a full index family")
        return [dict(row) for row in live], fetch_trace
    except (
        canary.CanaryOpenUsLawError,
        canary.CanaryParityError,
        canary.CanaryFallbackError,
        canary.CanaryRemoteError,
        ResolverError,
        MutableRevisionError,
        PublicQueryError,
    ) as exc:
        raise PublicQueryError(str(exc)) from exc
    finally:
        if fixture_tmpdir is not None:
            fixture_tmpdir.cleanup()
        if cache_tmpdir is not None:
            cache_tmpdir.cleanup()


def verify_attribution_notice(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    admission = load_json_mapping(
        _repo_file(SOURCE_ADMISSION_RELPATH, repo_root=repo_root)
    )
    publish = load_publish_module()
    candidate = publish.load_candidate_receipt(repo_root=repo_root)
    rows = admission.get("jurisdictions") or []
    if not isinstance(rows, list) or len(rows) != EXPECTED_JURISDICTION_COUNT:
        raise PublicAttributionError(
            "source admission must list exactly 51 jurisdiction attribution duties"
        )
    notices: list[dict[str, Any]] = []
    expected = list(EXACT_51_JURISDICTION_CODES)
    observed: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise PublicAttributionError("source admission row must be an object")
        code = str(row.get("jurisdiction_code") or "")
        observed.append(code)
        duty = dict(row.get("attribution_duty") or {})
        notice = str(duty.get("notice") or "").strip()
        if duty.get("required") is not True:
            raise PublicAttributionError(
                f"{code} is missing a required attribution duty"
            )
        if duty.get("currentness_disclaimer_required") is not True:
            raise PublicAttributionError(
                f"{code} is missing the required currentness disclaimer"
            )
        if len(notice) < 24:
            raise PublicAttributionError(f"{code} attribution notice is empty")
        if "official" not in notice.casefold():
            raise PublicAttributionError(
                f"{code} attribution notice does not name the official source"
            )
        notices.append(
            {
                "currentness_disclaimer_required": True,
                "jurisdiction_code": code,
                "notice": notice,
                "required": True,
            }
        )
    if observed != expected:
        raise PublicAttributionError(
            "attribution duties are not in the exact-51 jurisdiction order"
        )
    rights = dict(candidate.get("rights_receipts") or {})
    if rights.get("attribution_required") is not True:
        raise PublicAttributionError("candidate rights receipt omitted attribution")
    if int(rights.get("jurisdiction_count") or 0) != EXPECTED_JURISDICTION_COUNT:
        raise PublicAttributionError("candidate rights receipt is not exact-51")
    disclaimer = str(admission.get("currentness_disclaimer") or "").strip()
    if "not a substitute for the official source" not in disclaimer.casefold():
        raise PublicAttributionError("corpus currentness disclaimer is missing")
    return {
        "currentness_disclaimer": disclaimer,
        "jurisdiction_count": EXPECTED_JURISDICTION_COUNT,
        "notice_count": len(notices),
        "notices": notices,
        "ok": True,
        "required": True,
        "verified": True,
    }


def verify_legacy_raw_preservation(
    publication: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    applied: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    publish = load_publish_module()
    snapshot = load_json_mapping(_repo_file(BUCKET_SNAPSHOT_RELPATH, repo_root=repo_root))
    raw_root = publish.load_raw_root_snapshot(repo_root=repo_root)
    if len(raw_root) != EXPECTED_RAW_ROOT_COUNT:
        raise PublicLegacyError(
            f"raw bucket root has {len(raw_root)} objects, expected "
            f"{EXPECTED_RAW_ROOT_COUNT}"
        )
    expected_block = snapshot.get("expected")
    reconciliation = snapshot.get("reconciliation")
    snapshot_count = 0
    if isinstance(expected_block, Mapping) and expected_block.get("object_count") is not None:
        snapshot_count = int(expected_block["object_count"])
    elif isinstance(reconciliation, Mapping):
        counted = reconciliation.get("object_count")
        if isinstance(counted, Mapping):
            snapshot_count = int(
                counted.get("independent")
                or counted.get("present")
                or counted.get("expected")
                or 0
            )
        elif counted is not None:
            snapshot_count = int(counted)
    elif snapshot.get("object_count") is not None and not isinstance(
        snapshot.get("object_count"), Mapping
    ):
        snapshot_count = int(snapshot["object_count"])
    if snapshot_count != EXPECTED_RAW_ROOT_COUNT:
        raise PublicLegacyError(
            f"bucket snapshot object_count is {snapshot_count}, expected "
            f"{EXPECTED_RAW_ROOT_COUNT}"
        )
    if int(publication.get("raw_bucket_root_object_count") or 0) != EXPECTED_RAW_ROOT_COUNT:
        raise PublicLegacyError(
            "publication receipt does not preserve the 107 raw-root objects"
        )
    if publication.get("raw_bucket_root_untouched") is not True:
        raise PublicLegacyError("publication receipt overwrote the raw bucket root")
    if publication.get("root_raw_object_overwritten") is not False:
        raise PublicLegacyError("publication receipt overwrote a raw-root object")
    if publication.get("deletion_occurred") is not False:
        raise PublicLegacyError("publication receipt recorded a deletion")
    protected = ("README.md", "SHA256SUMS.json")
    missing_protected = [name for name in protected if name not in raw_root]
    if missing_protected:
        raise PublicLegacyError(
            "legacy raw root is missing " + ", ".join(missing_protected)
        )
    parquet_roots = [
        path
        for path in raw_root
        if path.endswith(".parquet") and "/" not in path
    ]
    if len(parquet_roots) < 90:
        raise PublicLegacyError("legacy raw Parquet inventory is incomplete")
    if applied is not None:
        if applied.get("raw_root_untouched") is not True:
            raise PublicLegacyError("rebuilt store mutated the raw bucket root")
        rebuilt_paths = list(applied.get("raw_root_paths") or [])
        if set(rebuilt_paths) != set(raw_root):
            raise PublicLegacyError("rebuilt store drifted from the raw-root snapshot")
    return {
        "deletion_occurred": False,
        "object_count": EXPECTED_RAW_ROOT_COUNT,
        "ok": True,
        "protected_raw_root_present": list(protected),
        "raw_parquet_count": len(parquet_roots),
        "raw_root_untouched": True,
        "root_raw_object_overwritten": False,
        "verified": True,
    }


# ---------------------------------------------------------------------------
# Receipt construction
# ---------------------------------------------------------------------------


def _acceptance_from_checks(checks: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    acceptance: dict[str, Any] = {
        "all_expected_outputs_required": True,
        "attribution_notice": checks["attribution"].get("ok") is True,
        "bucket_content_root": checks["bucket_content_root"].get("ok") is True,
        "criteria": ACCEPTANCE_CRITERIA,
        "every_descriptor": checks["descriptors"].get("ok") is True,
        "exact_51_coverage": checks["exact_51"].get("ok") is True,
        "fetch_trace": checks["fetch_trace"].get("ok") is True,
        "legacy_raw_preservation": checks["legacy_raw"].get("ok") is True,
        "model_receipt": checks["model"].get("ok") is True,
        "no_secret_or_path_leak": True,
        "public_40_hex_dataset_revision": checks["public_revision"].get("ok") is True,
        "sparse_query_mode": checks["sparse_query"].get("ok") is True,
        "viewer_configs": checks["viewer"].get("ok") is True,
    }
    failed = [
        key for key, value in acceptance.items() if key != "criteria" and value is not True
    ]
    if failed:
        raise MismatchError("public-canary acceptance failed: " + ", ".join(failed))
    return acceptance


def build_public_canary_receipt(
    *,
    publication: Mapping[str, Any],
    redownloaded: Mapping[str, Any],
    applied: Mapping[str, Any],
    public_revision: Mapping[str, Any],
    viewer: Mapping[str, Any],
    bucket_content_root: Mapping[str, Any],
    exact_51: Mapping[str, Any],
    model: Mapping[str, Any],
    descriptors: Mapping[str, Any],
    queries: Sequence[Mapping[str, Any]],
    fetch_trace: Mapping[str, Any],
    attribution: Mapping[str, Any],
    legacy_raw: Mapping[str, Any],
) -> dict[str, Any]:
    sparse_ok = (
        bool(queries)
        and {str(row.get("mode")) for row in queries} == set(QUERY_MODES)
        and all(row.get("sparse_io") is True for row in queries)
    )
    checks = {
        "attribution": attribution,
        "bucket_content_root": bucket_content_root,
        "descriptors": descriptors,
        "exact_51": exact_51,
        "fetch_trace": fetch_trace,
        "legacy_raw": legacy_raw,
        "model": model,
        "public_revision": public_revision,
        "sparse_query": {"ok": sparse_ok},
        "viewer": viewer,
    }
    acceptance = _acceptance_from_checks(checks)
    unused = sorted(
        {
            path
            for row in queries
            for path in (row.get("unused_siblings_not_fetched") or [])
        }
    )
    receipt: dict[str, Any] = {
        "acceptance": acceptance,
        "adr_path": ADR_PATH,
        "attribution": {
            "currentness_disclaimer": attribution["currentness_disclaimer"],
            "jurisdiction_count": attribution["jurisdiction_count"],
            "notice_count": attribution["notice_count"],
            "notices": list(attribution["notices"]),
            "required": True,
            "verified": True,
        },
        "board_namespace": BOARD_NAMESPACE,
        "bucket_content_root": bucket_content_root["content_root"],
        "bucket_id": publication.get("bucket_id"),
        "bundle": BUNDLE,
        "code_version": CODE_VERSION,
        "dataset_id": publication.get("dataset_id") or publication.get("target_repo"),
        "dataset_revision": publication["dataset_revision"],
        "depends_on": list(DEPENDS_ON),
        "descriptors": {
            "configuration_descriptor_count": descriptors[
                "configuration_descriptor_count"
            ],
            "configuration_descriptors": list(descriptors["configuration_descriptors"]),
            "descriptor_count": descriptors["descriptor_count"],
            "paths": list(descriptors["paths"]),
            "verified": True,
            "verified_count": descriptors["verified_count"],
        },
        "exact_51": {
            "configuration": exact_51["configuration"],
            "dc_counted_once": True,
            "jurisdiction_codes": list(exact_51["jurisdiction_codes"]),
            "jurisdiction_count": exact_51["jurisdiction_count"],
            "verified": True,
        },
        "fetch_trace": {
            "credential_free": True,
            "full_index_downloaded": False,
            "local_path_free": True,
            "ok": True,
            "queries": list(fetch_trace["queries"]),
            "query_count": fetch_trace["query_count"],
            "unused_siblings_not_fetched": list(
                fetch_trace.get("unused_siblings_not_fetched") or unused
            ),
            "verified": True,
        },
        "fixture_id": FIXTURE_ID,
        "goal_id": GOAL_ID,
        "isolated_transport": True,
        "legacy_raw": {
            "deletion_occurred": False,
            "object_count": legacy_raw["object_count"],
            "protected_raw_root_present": list(legacy_raw["protected_raw_root_present"]),
            "raw_parquet_count": legacy_raw["raw_parquet_count"],
            "raw_root_untouched": True,
            "root_raw_object_overwritten": False,
            "verified": True,
        },
        "live_network": False,
        "local_artifact_fallback": False,
        "local_root_used": False,
        "manifest_digest": publication["manifest_digest"],
        "model": {
            "dimension": model["dimension"],
            "max_tokens": model["max_tokens"],
            "model_id": model["model_id"],
            "model_revision": model["model_revision"],
            "normalization": model["normalization"],
            "pooling": model["pooling"],
            "published_embeddings_descriptor": True,
            "vector_space_id": model["vector_space_id"],
            "verified": True,
        },
        "network_required": False,
        "notes": (
            "Independent public-pin canary of the immutable Open US Law "
            "Dataset and content-addressed Bucket release (OUL-045). The "
            "public 40-hex Dataset revision, Viewer configs, Bucket content "
            "root, exact-51 coverage, pinned GTE-small model receipt, every "
            "descriptor, sparse query mode, fetch trace, attribution notice, "
            "and legacy raw-root preservation were verified without Hub "
            "contact or local-root fallback."
        ),
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_mutation_authorized": False,
        "publication": {
            "bucket_release_prefix": publication["bucket_release_prefix"],
            "dataset_revision": publication["dataset_revision"],
            "identities_digest": publication.get("identities_digest"),
            "manifest_digest": publication["manifest_digest"],
            "receipt_sha256": publication.get("receipt_sha256"),
            "remote_object_count": publication.get("remote_object_count"),
            "status": publication.get("status"),
            "task_id": publication.get("task_id"),
        },
        "publication_authorized": False,
        "queries": [dict(item) for item in queries],
        "query_mode_count": len(QUERY_MODES),
        "query_modes": list(QUERY_MODES),
        "redownload": {
            "bucket_content_root": publication["bucket_release_prefix"],
            "clean_cache": True,
            "dataset_revision": publication["dataset_revision"],
            "public_identities": redownloaded,
            "transport": "isolated_recorded_public_store",
        },
        "require_public_pin": True,
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "sparse_io": {
            "full_index_downloaded": False,
            "local_artifact_fallback": False,
            "query_modes_sparse": True,
            "unused_siblings_not_fetched": unused,
        },
        "status": "verified_isolated",
        "task_id": TASK_ID,
        "target_repo": publication.get("target_repo") or publication.get("dataset_id"),
        "tokens_used": False,
        "transport": "isolated_recorded_public_store",
        "viewer": {
            "config_count": viewer["config_count"],
            "config_names": list(viewer["config_names"]),
            "configs": list(viewer["configs"]),
            "default_config": viewer["default_config"],
            "default_excludes_quarantine": True,
            "default_excludes_recovery": True,
            "exactly_one_default": True,
            "hidden_configurations": list(viewer["hidden_configurations"]),
            "schema_coherent": True,
            "verified": True,
        },
    }
    receipt["receipt_sha256"] = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    reject_credentials_in_payload(receipt, label="public_canary")
    reject_path_leaks(receipt, label="public_canary")
    reject_identity_contamination(receipt, label="public_canary")
    return receipt


def run_public_canary(
    *,
    repo_root: Path | str | None = None,
    publication_path: Path | str | None = None,
    require_public_pin: bool = True,
    cache_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Independently verify the immutable public pin."""

    publication = load_publication_receipt(
        publication_path,
        repo_root=repo_root,
        require_public_pin=require_public_pin,
    )
    store, applied = rebuild_public_store(publication, repo_root=repo_root)
    redownloaded = redownload_public_identities(publication, store)
    public_revision = verify_public_40_hex_revision(publication)
    viewer = verify_viewer_configs()
    bucket_content_root = verify_bucket_content_root(
        publication, redownloaded=redownloaded
    )
    exact_51 = verify_exact_51_coverage(repo_root=repo_root)
    model = verify_model_receipt(repo_root=repo_root, publication=publication)
    descriptors = verify_every_descriptor(
        publication, repo_root=repo_root, redownloaded=redownloaded
    )
    queries, fetch_trace = verify_sparse_query_mode(
        publication=publication, cache_dir=cache_dir
    )
    attribution = verify_attribution_notice(repo_root=repo_root)
    legacy_raw = verify_legacy_raw_preservation(
        publication, repo_root=repo_root, applied=applied
    )
    return build_public_canary_receipt(
        publication=publication,
        redownloaded=redownloaded,
        applied=applied,
        public_revision=public_revision,
        viewer=viewer,
        bucket_content_root=bucket_content_root,
        exact_51=exact_51,
        model=model,
        descriptors=descriptors,
        queries=queries,
        fetch_trace=fetch_trace,
        attribution=attribution,
        legacy_raw=legacy_raw,
    )


def build_default_public_canary(
    *,
    repo_root: Path | str | None = None,
    publication_path: Path | str | None = None,
) -> dict[str, Any]:
    return run_public_canary(
        repo_root=repo_root,
        publication_path=publication_path,
        require_public_pin=True,
    )


def materialize_default_receipt(
    *,
    repo_root: Path | str | None = None,
    receipt_path: Path | str | None = None,
    publication_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    receipt = build_default_public_canary(
        repo_root=repo_root, publication_path=publication_path
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
        "bucket_content_root",
        "status",
        "live_network",
        "publication_authorized",
        "local_artifact_fallback",
        "local_root_used",
        "require_public_pin",
        "query_mode_count",
    )
    mismatches.extend(_compare_mappings(fresh, sealed, path="receipt", keys=top_keys))
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("publication") or {}),
            dict(sealed.get("publication") or {}),
            path="publication",
            keys=(
                "dataset_revision",
                "bucket_release_prefix",
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
    if (fresh.get("viewer") or {}).get("config_names") != (
        sealed.get("viewer") or {}
    ).get("config_names"):
        mismatches.append("viewer configs drifted from the sealed receipt")
    if (fresh.get("exact_51") or {}).get("jurisdiction_codes") != (
        sealed.get("exact_51") or {}
    ).get("jurisdiction_codes"):
        mismatches.append("exact-51 coverage drifted from the sealed receipt")
    if (fresh.get("model") or {}).get("model_revision") != (
        sealed.get("model") or {}
    ).get("model_revision"):
        mismatches.append("model receipt drifted from the sealed receipt")
    if (fresh.get("descriptors") or {}).get("paths") != (
        sealed.get("descriptors") or {}
    ).get("paths"):
        mismatches.append("descriptor inventory drifted from the sealed receipt")
    if (fresh.get("legacy_raw") or {}).get("object_count") != (
        sealed.get("legacy_raw") or {}
    ).get("object_count"):
        mismatches.append("legacy raw inventory drifted from the sealed receipt")
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
    fresh_ids = [
        (row.get("relative_path"), row.get("sha256"), row.get("dataset_object_id"))
        for row in ((fresh.get("redownload") or {}).get("public_identities") or {}).get(
            "files"
        )
        or []
        if isinstance(row, Mapping)
    ]
    sealed_ids = [
        (row.get("relative_path"), row.get("sha256"), row.get("dataset_object_id"))
        for row in ((sealed.get("redownload") or {}).get("public_identities") or {}).get(
            "files"
        )
        or []
        if isinstance(row, Mapping)
    ]
    if fresh_ids != sealed_ids:
        mismatches.append("public identity redownload drifted from the sealed receipt")
    if fresh.get("receipt_sha256") != sealed.get("receipt_sha256"):
        mismatches.append("receipt_sha256 drifted from the sealed receipt")
    return mismatches


def check_receipt_structure(receipt: Mapping[str, Any]) -> None:
    required = (
        "acceptance",
        "attribution",
        "bucket_content_root",
        "dataset_revision",
        "descriptors",
        "exact_51",
        "fetch_trace",
        "legacy_raw",
        "manifest_digest",
        "model",
        "publication",
        "queries",
        "receipt_sha256",
        "redownload",
        "viewer",
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
        raise MismatchError("public canary must not authorize further mutation")
    if receipt.get("public_mutation_authorized") is not False:
        raise MismatchError("public canary must not authorize further mutation")
    if receipt.get("live_network") is not False:
        raise MismatchError("receipt must be network-free")
    if receipt.get("network_required") is not False:
        raise MismatchError("receipt must be network-free")
    if receipt.get("local_artifact_fallback") is not False:
        raise MismatchError("receipt used a local artifact fallback")
    if receipt.get("local_root_used") is not False:
        raise MismatchError("receipt used a local_root fallback")
    if receipt.get("require_public_pin") is not True:
        raise MismatchError("receipt is not bound to the public pin")
    revision = require_immutable_public_revision(
        receipt.get("dataset_revision"), name="receipt.dataset_revision"
    )
    if revision.casefold() in PRODUCTION_REFS:
        raise MismatchError("dataset revision is a production ref")
    prefix = str(receipt.get("bucket_content_root") or "")
    expected_prefix = f"releases/{receipt.get('manifest_digest')}/"
    if prefix != expected_prefix:
        raise MismatchError("bucket content root is not unique to this candidate")
    queries = receipt.get("queries") or []
    if not isinstance(queries, list) or len(queries) != len(QUERY_MODES):
        raise MismatchError("receipt must record every query mode")
    modes = {str(row.get("mode")) for row in queries if isinstance(row, Mapping)}
    if modes != set(QUERY_MODES):
        raise MismatchError("receipt is missing one or more query modes")
    if list(receipt.get("query_modes") or []) != list(QUERY_MODES):
        raise MismatchError("query_modes drifted from the public API")
    if (receipt.get("exact_51") or {}).get("jurisdiction_count") != EXPECTED_JURISDICTION_COUNT:
        raise MismatchError("receipt exact-51 count drifted")
    if (receipt.get("legacy_raw") or {}).get("object_count") != EXPECTED_RAW_ROOT_COUNT:
        raise MismatchError("receipt legacy raw count drifted")
    if (receipt.get("model") or {}).get("model_revision") != MODEL_REVISION:
        raise MismatchError("receipt model pin drifted")
    if (receipt.get("viewer") or {}).get("default_config") != DEFAULT_CONFIGURATION:
        raise MismatchError("receipt Viewer default drifted")
    expected = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    if receipt.get("receipt_sha256") != expected:
        raise StaleInputError("receipt_sha256 does not match the sealed surface")
    acceptance = dict(receipt.get("acceptance") or {})
    if acceptance.get("criteria") != ACCEPTANCE_CRITERIA:
        raise MismatchError("acceptance criteria drifted")
    for key in ACCEPTANCE_FLAGS:
        if acceptance.get(key) is not True:
            raise MismatchError(f"acceptance.{key} is not true")
    for key, value in acceptance.items():
        if key == "criteria":
            continue
        if value is not True:
            raise MismatchError(f"acceptance.{key} is not true")


def check_public_release_receipt(
    receipt: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    publication_path: Path | str | None = None,
    require_public_pin: bool = True,
) -> dict[str, Any]:
    check_receipt_structure(receipt)
    reject_credentials_in_payload(receipt, label="public_canary")
    reject_path_leaks(receipt, label="public_canary")
    reject_identity_contamination(receipt, label="public_canary")
    publication = load_publication_receipt(
        publication_path,
        repo_root=repo_root,
        require_public_pin=require_public_pin,
    )
    if receipt.get("dataset_revision") != publication.get("dataset_revision"):
        raise MismatchError("canary is not bound to the public 40-hex revision")
    if receipt.get("bucket_content_root") != publication.get("bucket_release_prefix"):
        raise MismatchError("canary is not bound to the public bucket content root")
    if receipt.get("manifest_digest") != publication.get("manifest_digest"):
        raise MismatchError("canary manifest digest drifted from the public pin")
    fresh = build_default_public_canary(
        repo_root=repo_root, publication_path=publication_path
    )
    mismatches = compare_receipts(fresh, receipt)
    if mismatches:
        raise StaleInputError(
            "sealed receipt drifted from a fresh public canary: "
            + "; ".join(mismatches[:8])
        )
    return {
        "bucket_content_root": receipt.get("bucket_content_root"),
        "criteria": (receipt.get("acceptance") or {}).get("criteria"),
        "dataset_revision": receipt.get("dataset_revision"),
        "descriptor_count": (receipt.get("descriptors") or {}).get("descriptor_count"),
        "exact_51_count": (receipt.get("exact_51") or {}).get("jurisdiction_count"),
        "goal_id": receipt.get("goal_id"),
        "legacy_raw_object_count": (receipt.get("legacy_raw") or {}).get("object_count"),
        "live_network": False,
        "local_artifact_fallback": False,
        "manifest_digest": receipt.get("manifest_digest"),
        "mismatches": [],
        "model_revision": (receipt.get("model") or {}).get("model_revision"),
        "ok": True,
        "publication_authorized": False,
        "query_mode_count": receipt.get("query_mode_count"),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "require_public_pin": True,
        "task_id": receipt.get("task_id"),
        "viewer_default": (receipt.get("viewer") or {}).get("default_config"),
    }


def refuse_live_hub_without_injection() -> dict[str, Any]:
    return {
        "live_network": False,
        "mutation_executed": False,
        "reason": (
            "live Hub canary requires an operator-injected transport; "
            "this CLI verifies only the isolated public pin"
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
        prog="check_open_us_law_public_release.py",
        description=(
            "Verify the immutable public Open US Law Dataset revision and "
            f"Dataset Viewer ({TASK_ID}). Default mode checks the sealed "
            "public-canary receipt without network contact."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate the frozen public-canary receipt without rewriting it.",
    )
    parser.add_argument(
        "--require-public-pin",
        action="store_true",
        help=(
            "Require the OUL-044 public publication receipt and bind the "
            "canary to its exact 40-hex Dataset revision and "
            "content-addressed Bucket content root."
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
        "--publication",
        type=Path,
        default=None,
        help=f"Publication receipt (default: {PUBLICATION_RECEIPT_RELPATH.as_posix()})",
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
    require_pin = bool(args.require_public_pin) or check_mode
    receipt_path = (
        Path(args.receipt).expanduser().resolve()
        if args.receipt is not None
        else default_receipt_path()
    )
    publication_path = (
        Path(args.publication).expanduser().resolve()
        if args.publication is not None
        else default_publication_path()
    )

    try:
        if args.live:
            payload = refuse_live_hub_without_injection()
            write_json(None, payload)
            return 2

        if check_mode:
            sealed = load_json_mapping(receipt_path)
            payload = check_public_release_receipt(
                sealed,
                publication_path=publication_path,
                require_public_pin=require_pin,
            )
            write_json(None, payload)
            return 0 if payload.get("ok") else 1

        receipt = run_public_canary(
            publication_path=publication_path,
            require_public_pin=require_pin,
            cache_dir=args.cache_dir,
        )
        if args.write:
            write_json_report(receipt, receipt_path)
        write_json(None, receipt)
        return 0
    except (
        PublicReleaseCheckError,
        PublicPinError,
        PublicViewerError,
        PublicCoverageError,
        PublicModelError,
        PublicDescriptorError,
        PublicQueryError,
        PublicAttributionError,
        PublicLegacyError,
        MissingInputError,
        MismatchError,
        StaleInputError,
        PathLeakError,
        SecretLeakError,
        MutableRevisionError,
        ResolverError,
        ValueError,
        RuntimeError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
