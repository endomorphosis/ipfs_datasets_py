#!/usr/bin/env python3
"""Publish the authorized Open US Law Dataset and Bucket release (OUL-044).

This is the only public mutation task. After immediate publication-gate
revalidation of the OUL-043 prepublication seal, it:

1. Commits the exact staged bytes to
   ``justicedao/open-us-law-sparse-graphrag`` (create + additive commit).
2. Copies those same bytes additively under
   ``releases/<manifest_sha256>/`` in ``justicedao/open-us-law-bucket``.
3. Updates the tiny ``LATEST.json`` pointer **last**, only after the
   prefix is complete and redownload-verified.

Deletion, force-push, history rewrite, visibility change, and raw-root
overwrite are structurally impossible. Default mode is an isolated
recorded transport (no Hub contact). Live Hub mutation remains opt-in
and fail-closed.

Validation gate (no network)::

    python scripts/ops/legal_data/publish_open_us_law_hf_release.py --check-receipt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, TypeVar

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_publication_gate import (  # noqa: E402
    AUTHORIZED_BUCKET_ID,
    AUTHORIZED_DATASET_REPO_ID,
    AUTHORIZED_OPERATIONS,
    BUCKET_POINTER_PATH,
    BUCKET_RELEASE_PREFIX_TEMPLATE,
    FORBIDDEN_OPERATIONS,
    PublicationGateDeniedError,
    PublicationPhase,
    authorize_and_mutate,
    credentials_scope_for,
    evaluate_publication_gate,
    is_protected_raw_root_path,
    release_prefix_for,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (  # noqa: E402
    ADR_PATH,
    DEFAULT_DATASET_REPO_ID,
    SOURCE_BUCKET,
    digest_mapping,
    normalize_sha256,
    require_immutable_revision,
)

# ---------------------------------------------------------------------------
# Identity / sealed policy
# ---------------------------------------------------------------------------

TASK_ID: Final = "OUL-044"
GOAL_ID: Final = "OUL-G080"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "publish_open_us_law_hf_release.py"
CODE_VERSION: Final = "1"
BUNDLE: Final = "public-upload"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("OUL-043",)

RECEIPT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-publication-receipt@1"
SCHEMA_VERSION: Final = "open-us-law-publication-receipt/v1"
PUBLISH_PLAN_SCHEMA: Final = "ipfs_datasets_py/open-us-law-publish-plan@1"
POINTER_SCHEMA: Final = "ipfs_datasets_py/open-us-law-release-pointer@1"
FIXTURE_ID: Final = "open-us-law-publication-receipt-v1"

DEFAULT_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/publication_receipt.json"
)
SEAL_RELPATH: Final = Path("docs/reports/open_us_law_reindex/prepublication_seal.json")
STAGING_RELPATH: Final = Path("docs/reports/open_us_law_reindex/staging_upload.json")
CANDIDATE_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/release_candidate.json"
)
BUCKET_SNAPSHOT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/bucket_snapshot.json"
)

DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_BUCKET_ID: Final = SOURCE_BUCKET
MAX_POINTER_BYTES: Final = 2048
AUTHORIZATION_ENV: Final = "OPEN_US_LAW_PUBLICATION_AUTHORIZATION"
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

SEAL_SCHEMA: Final = "ipfs_datasets_py/open-us-law-prepublication-seal@1"
STAGING_SCHEMA: Final = "ipfs_datasets_py/open-us-law-staging-upload@1"
CANDIDATE_SCHEMA: Final = "ipfs_datasets_py/open-us-law-release-candidate@1"
SEAL_TIMING: Final = "before_mutation"

ALLOWED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        "dataset_create",
        "dataset_additive_commit",
        "bucket_release_prefix_write",
        "bucket_pointer_update_last",
        "add_only_upload",
    }
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
    }
)

ACCEPTANCE_CRITERIA: Final = (
    "After immediate gate revalidation, the exact staged bytes are "
    "committed to justicedao/open-us-law-sparse-graphrag and copied "
    "additively under releases/<manifest_sha256>/ in "
    "justicedao/open-us-law-bucket; a tiny pointer is updated last, "
    "no root raw object is overwritten, and no deletion occurs."
)

DATASET_PRINCIPAL_IDENTITY: Final = f"env:{AUTHORIZED_DATASET_REPO_ID}"
BUCKET_PRINCIPAL_IDENTITY: Final = f"env:{AUTHORIZED_BUCKET_ID}"

T = TypeVar("T")

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
        "authorizing_for_publication",
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
_UTC_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
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


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PublishOpenUsLawError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class PublishAuthorizationError(PublishOpenUsLawError):
    """Raised when live mutation is attempted without opt-in authorization."""


class PublishSafetyError(PublishOpenUsLawError):
    """Raised when a plan would delete, overwrite root, or skip the pointer last."""


class PublishSealError(PublishOpenUsLawError):
    """Raised when the prepublication seal cannot authorize public mutation."""


class PublishPlanReviewError(PublishOpenUsLawError):
    """Raised when apply is requested without a matching reviewed plan digest."""


class MissingInputError(PublishOpenUsLawError):
    """Raised when a required producer input is absent."""


class MismatchError(PublishOpenUsLawError):
    """Raised when a bound digest or field does not match."""


class StaleInputError(PublishOpenUsLawError):
    """Raised when a receipt drifted from a fresh rebuild."""


class PathLeakError(PublishOpenUsLawError):
    """Raised when absolute local paths appear in a public receipt."""


class SecretLeakError(PublishOpenUsLawError):
    """Raised when credential-like material appears in a public receipt."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def default_seal_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / SEAL_RELPATH).resolve()


def default_staging_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / STAGING_RELPATH).resolve()


def default_candidate_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / CANDIDATE_RELPATH).resolve()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise MissingInputError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishOpenUsLawError(f"cannot read JSON {target.name}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise PublishOpenUsLawError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def write_json_report(payload: Mapping[str, Any], path: Path) -> Path:
    reject_credentials_in_payload(payload, label="publication_receipt")
    reject_path_leaks(payload, label="publication_receipt")
    reject_identity_contamination(payload, label="publication_receipt")
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


def _verify_receipt_digest(
    payload: Mapping[str, Any], *, digest_key: str
) -> None:
    expected = digest_mapping(
        {key: value for key, value in payload.items() if key != digest_key}
    )
    if payload.get(digest_key) != expected:
        raise StaleInputError(f"{digest_key} does not match the sealed surface")


def _parse_utc(value: str) -> datetime:
    if not _UTC_RE.fullmatch(value):
        raise PublishSealError(f"timestamp must be YYYY-MM-DDTHH:MM:SSZ: {value!r}")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


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


def reject_identity_contamination(value: Any, *, label: str = "publication") -> None:
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
        raise PublishOpenUsLawError(
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
    joined = " ".join(str(item) for item in argv)
    for env_name in SECRET_ENV_NAMES:
        env_val = os.environ.get(env_name)
        if env_val and env_val in joined:
            raise SecretLeakError(
                f"refusing to accept ${env_name} value on the command line"
            )


# ---------------------------------------------------------------------------
# Normalization / safety
# ---------------------------------------------------------------------------


def _normalize_dataset_id(value: str, *, label: str = "target_repo") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise PublishOpenUsLawError(f"{label} must be owner/name, got {value!r}")
    return text


def _assert_operations_authorized(operations: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in operations:
        op = str(raw or "").strip().casefold().replace("-", "_")
        if not op:
            continue
        if op in FORBIDDEN_OPERATIONS or op.startswith("delete") or "force" in op:
            raise PublishSafetyError(
                f"operation is forbidden for Open US Law publication: {raw!r}"
            )
        if "visibility" in op:
            raise PublishSafetyError(
                f"visibility changes are impossible via publication: {raw!r}"
            )
        if op not in ALLOWED_OPERATIONS:
            raise PublishSafetyError(
                f"only authorized additive operations are permitted; got {raw!r}"
            )
        normalized.append(op)
    if not normalized:
        raise PublishSafetyError("publish plan requires at least one allowed operation")
    return tuple(sorted(set(normalized)))


def assert_mutation_authorized(
    *,
    authorize_mutation: bool,
    authorization_env: str = AUTHORIZATION_ENV,
) -> None:
    if not authorize_mutation:
        raise PublishAuthorizationError(
            "mutation refused: pass --authorize-mutation and set "
            f"${authorization_env} (credentials remain environment-only)"
        )
    token = os.environ.get(authorization_env, "").strip()
    if not token:
        raise PublishAuthorizationError(
            f"mutation refused: ${authorization_env} is empty or unset"
        )


def content_cid_for(digest: str) -> str:
    return f"sha256:{normalize_sha256(digest, name='content_cid')}"


def dataset_object_id(*, repo_id: str, revision: str, path: str, sha256: str) -> str:
    return f"dataset:{repo_id}@{revision}:{path}#{sha256}"


def bucket_object_id(*, bucket_id: str, path: str, sha256: str) -> str:
    return f"bucket:{bucket_id}:{path}#{sha256}"


def derive_public_dataset_revision(
    *,
    manifest_digest: str,
    plan_digest: str,
    staging_revision: str,
) -> str:
    """Return a deterministic 40-hex public Dataset commit."""

    digest = digest_mapping(
        {
            "kind": "public_dataset_additive_commit",
            "manifest_digest": manifest_digest,
            "plan_digest": plan_digest,
            "program_id": PROGRAM_ID,
            "staging_revision": staging_revision,
            "task_id": TASK_ID,
        }
    )
    revision = digest[:40]
    return require_immutable_revision(revision, name="dataset_revision")


# ---------------------------------------------------------------------------
# Isolated additive public release store
# ---------------------------------------------------------------------------


class IsolatedPublicReleaseStore:
    """In-process isolated Dataset + Bucket store for the public release.

    Additive only. Raw-root objects are snapshotted and never overwritten.
    ``LATEST.json`` may be written only after the release prefix is complete
    and redownload-verified. Deletion is impossible.
    """

    def __init__(self, raw_root_objects: Mapping[str, str] | None = None) -> None:
        self.dataset: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.bucket: dict[tuple[str, str], dict[str, Any]] = {}
        snapshot = {str(k): str(v) for k, v in dict(raw_root_objects or {}).items()}
        self.raw_root_before = dict(snapshot)
        self.raw_root_after = dict(snapshot)
        self.created_datasets: set[str] = set()
        self.prefix_complete = False
        self.prefix_redownload_verified = False
        self.pointer_updated = False
        self.pointer_updated_last = False
        self.deletion_occurred = False
        self.operation_sequence: list[str] = []

    def create_dataset(self, *, repo_id: str) -> dict[str, Any]:
        if self.pointer_updated:
            raise PublishSafetyError("dataset create after pointer update is forbidden")
        repo = _normalize_dataset_id(repo_id, label="dataset_repo_id")
        if repo != AUTHORIZED_DATASET_REPO_ID:
            raise PublishSafetyError(
                f"dataset create target {repo!r} is not the authorized Dataset"
            )
        self.created_datasets.add(repo)
        self.operation_sequence.append("dataset_create")
        return {
            "created": True,
            "existed_before": False,
            "operation": "dataset_create",
            "repo_id": repo,
        }

    def add_dataset(
        self,
        *,
        repo_id: str,
        revision: str,
        path: str,
        sha256: str,
        size_bytes: int | None,
        content_cid: str,
    ) -> dict[str, Any]:
        if self.pointer_updated:
            raise PublishSafetyError(
                "dataset write after pointer update is forbidden; pointer is last"
            )
        require_immutable_revision(revision, name="dataset_revision")
        if repo_id != AUTHORIZED_DATASET_REPO_ID:
            raise PublishSafetyError(
                f"dataset target {repo_id!r} is not the authorized Dataset"
            )
        key = (repo_id, revision, path)
        record = {
            "content_cid": content_cid,
            "object_id": dataset_object_id(
                repo_id=repo_id, revision=revision, path=path, sha256=sha256
            ),
            "operation": "dataset_additive_commit",
            "path": path,
            "repo_id": repo_id,
            "revision": revision,
            "sha256": sha256,
            "size_bytes": size_bytes,
        }
        existing = self.dataset.get(key)
        if existing is not None and existing["sha256"] != sha256:
            raise PublishSafetyError(
                f"additive dataset upload refused: {path} already exists with "
                "different bytes"
            )
        self.dataset[key] = record
        if "dataset_additive_commit" not in self.operation_sequence:
            self.operation_sequence.append("dataset_additive_commit")
        return dict(record)

    def add_bucket(
        self,
        *,
        bucket_id: str,
        path: str,
        sha256: str,
        size_bytes: int | None,
        content_cid: str,
    ) -> dict[str, Any]:
        if self.pointer_updated:
            raise PublishSafetyError(
                "bucket write after pointer update is forbidden; pointer is last"
            )
        posix = path.strip().lstrip("/")
        if posix == BUCKET_POINTER_PATH:
            raise PublishSafetyError(
                "pointer updates must go through update_pointer(), not add_bucket()"
            )
        if is_protected_raw_root_path(posix):
            raise PublishSafetyError(
                f"refusing protected raw bucket-root path {posix!r}"
            )
        if not posix.startswith("releases/"):
            raise PublishSafetyError(
                f"bucket writes must stay under {BUCKET_RELEASE_PREFIX_TEMPLATE}"
            )
        if posix in self.raw_root_after:
            raise PublishSafetyError(
                f"refusing to mutate raw bucket-root object {posix!r}"
            )
        if bucket_id != AUTHORIZED_BUCKET_ID:
            raise PublishSafetyError(
                f"bucket target {bucket_id!r} is not the authorized Bucket"
            )
        key = (bucket_id, posix)
        record = {
            "bucket_id": bucket_id,
            "content_cid": content_cid,
            "object_id": bucket_object_id(
                bucket_id=bucket_id, path=posix, sha256=sha256
            ),
            "operation": "bucket_release_prefix_write",
            "path": posix,
            "sha256": sha256,
            "size_bytes": size_bytes,
        }
        existing = self.bucket.get(key)
        if existing is not None and existing["sha256"] != sha256:
            raise PublishSafetyError(
                f"additive bucket upload refused: {posix} already exists with "
                "different bytes"
            )
        self.bucket[key] = record
        self.operation_sequence.append("bucket_release_prefix_write")
        return dict(record)

    def mark_prefix_complete(self, *, expected_paths: Sequence[str]) -> None:
        present = {path for (_bucket, path) in self.bucket}
        missing = [path for path in expected_paths if path not in present]
        if missing:
            raise PublishSafetyError(
                "release prefix is incomplete; missing "
                + ", ".join(missing[:8])
            )
        self.prefix_complete = True

    def redownload_verify_prefix(
        self,
        *,
        expected: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        if not self.prefix_complete:
            raise PublishSafetyError(
                "prefix redownload is refused until the prefix is complete"
            )
        verified: list[dict[str, Any]] = []
        for item in expected:
            path = str(item["path"])
            sha = str(item["sha256"])
            key = (str(item["bucket_id"]), path)
            record = self.bucket.get(key)
            if record is None:
                raise PublishSafetyError(
                    f"redownload failed: {path} is absent from the isolated bucket"
                )
            if record["sha256"] != sha:
                raise PublishSafetyError(
                    f"redownload digest mismatch for {path}"
                )
            verified.append(
                {
                    "object_id": record["object_id"],
                    "path": path,
                    "sha256": sha,
                    "verified": True,
                }
            )
        self.prefix_redownload_verified = True
        return {
            "object_count": len(verified),
            "prefix_redownload_verified": True,
            "verified_objects": verified,
        }

    def update_pointer(
        self,
        *,
        bucket_id: str,
        pointer: Mapping[str, Any],
        sha256: str,
        size_bytes: int,
        content_cid: str,
    ) -> dict[str, Any]:
        if not self.prefix_complete:
            raise PublishSafetyError(
                "LATEST.json may be updated only after the release prefix is complete"
            )
        if not self.prefix_redownload_verified:
            raise PublishSafetyError(
                "LATEST.json may be updated only after prefix redownload verification"
            )
        if self.pointer_updated:
            existing = self.bucket.get((bucket_id, BUCKET_POINTER_PATH))
            if existing is not None and existing["sha256"] == sha256:
                return dict(existing)
            raise PublishSafetyError("pointer already updated; rewrite is forbidden")
        if bucket_id != AUTHORIZED_BUCKET_ID:
            raise PublishSafetyError(
                f"pointer bucket {bucket_id!r} is not the authorized Bucket"
            )
        if is_protected_raw_root_path(BUCKET_POINTER_PATH) and (
            BUCKET_POINTER_PATH != "LATEST.json"
        ):
            raise PublishSafetyError("pointer path is a protected raw-root object")
        if BUCKET_POINTER_PATH in self.raw_root_before and is_protected_raw_root_path(
            BUCKET_POINTER_PATH
        ):
            raise PublishSafetyError("refusing to overwrite a protected raw-root pointer")
        if size_bytes > MAX_POINTER_BYTES:
            raise PublishSafetyError(
                f"pointer exceeds tiny-pointer budget ({size_bytes} > {MAX_POINTER_BYTES})"
            )
        _ = pointer
        record = {
            "bucket_id": bucket_id,
            "content_cid": content_cid,
            "object_id": bucket_object_id(
                bucket_id=bucket_id, path=BUCKET_POINTER_PATH, sha256=sha256
            ),
            "operation": "bucket_pointer_update_last",
            "path": BUCKET_POINTER_PATH,
            "sha256": sha256,
            "size_bytes": size_bytes,
        }
        self.bucket[(bucket_id, BUCKET_POINTER_PATH)] = record
        self.pointer_updated = True
        self.pointer_updated_last = True
        self.operation_sequence.append("bucket_pointer_update_last")
        return dict(record)

    def delete(self, *_args: Any, **_kwargs: Any) -> None:
        self.deletion_occurred = True
        raise PublishSafetyError("delete is forbidden for Open US Law publication")

    def raw_root_untouched(self) -> bool:
        return self.raw_root_before == self.raw_root_after

    def raw_root_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self.raw_root_before))

    def pointer_is_last(self) -> bool:
        if not self.operation_sequence:
            return False
        if self.operation_sequence[-1] != "bucket_pointer_update_last":
            return False
        return "bucket_pointer_update_last" not in self.operation_sequence[:-1]


# ---------------------------------------------------------------------------
# Producer loading
# ---------------------------------------------------------------------------


def load_candidate_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_candidate_path(repo_root)
    )
    receipt = load_json_mapping(target)
    if receipt.get("schema") != CANDIDATE_SCHEMA:
        raise MismatchError("candidate receipt schema mismatch")
    if receipt.get("task_id") != "OUL-040":
        raise MismatchError("candidate receipt is not the OUL-040 seal")
    if receipt.get("publication_authorized") is not False:
        raise PublishSafetyError("candidate receipt must not authorize public mutation")
    candidate = dict(receipt.get("candidate") or {})
    if not candidate.get("manifest_digest"):
        raise MismatchError("candidate receipt missing manifest_digest")
    normalize_sha256(str(candidate["manifest_digest"]), name="candidate.manifest")
    inventory = dict((receipt.get("artifact_digests") or {}).get("inventory") or {})
    if len(inventory) < 8:
        raise MismatchError("candidate artifact inventory is incomplete")
    _verify_receipt_digest(receipt, digest_key="receipt_sha256")
    return receipt


def load_staging_receipt(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_staging_path(repo_root)
    )
    receipt = load_json_mapping(target)
    if receipt.get("schema") != STAGING_SCHEMA:
        raise MismatchError("staging receipt schema mismatch")
    if receipt.get("task_id") != "OUL-041":
        raise MismatchError("staging receipt is not the OUL-041 upload")
    if receipt.get("publication_authorized") is not False:
        raise PublishSafetyError("staging receipt must not authorize public mutation")
    if receipt.get("public_mutation_authorized") is not False:
        raise PublishSafetyError("staging receipt must not authorize public mutation")
    if receipt.get("mutation_executed") is not True:
        raise PublishSafetyError("staging receipt did not execute the isolated apply")
    if receipt.get("status") != "staged_isolated":
        raise PublishSafetyError(
            f"staging status must be staged_isolated, got {receipt.get('status')!r}"
        )
    objects = receipt.get("remote_objects") or []
    if not isinstance(objects, list) or not objects:
        raise MismatchError("staging receipt is missing remote object identities")
    revision = require_immutable_revision(
        str(receipt.get("dataset_revision") or ""), name="staging.dataset_revision"
    )
    if revision.casefold() in PRODUCTION_REFS:
        raise PublishSafetyError("staging revision must not be a production ref")
    _verify_receipt_digest(receipt, digest_key="receipt_sha256")
    return receipt


def as_gate_seal(seal: Mapping[str, Any]) -> dict[str, Any]:
    """Return the compact publication-gate view of the prepublication seal."""

    nested = dict(seal.get("gate_seal") or {})
    if nested:
        return dict(nested)
    manifest = str(
        seal.get("manifest_digest")
        or seal.get("final_manifest_digest")
        or (seal.get("candidate") or {}).get("manifest_digest")
        or ""
    )
    return {
        "bucket_prefix": str(
            seal.get("bucket_prefix")
            or (seal.get("staging") or {}).get("bucket_staging_prefix")
            or ""
        ),
        "created_after_mutation": False,
        "created_before_mutation": True,
        "dataset_revision": str(
            seal.get("staging_revision")
            or (seal.get("staging") or {}).get("dataset_revision")
            or ""
        ),
        "final_manifest_digest": normalize_sha256(manifest, name="gate.manifest"),
        "future": False,
        "manifest_digest": normalize_sha256(manifest, name="gate.manifest"),
        "post_hoc": False,
        "present": True,
        "required_for_staging": False,
        "seal_timing": SEAL_TIMING,
        "substitutes_for_phase_evidence": False,
        "timing": SEAL_TIMING,
    }


def load_prepublication_seal(
    path: Path | str | None = None,
    *,
    repo_root: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    target = (
        Path(path).expanduser().resolve()
        if path is not None
        else default_seal_path(repo_root)
    )
    seal = load_json_mapping(target)
    revalidate_prepublication_seal(seal, now=now)
    return seal


def revalidate_prepublication_seal(
    seal: Mapping[str, Any],
    *,
    expected_manifest: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fail-closed immediate revalidation of the OUL-043 seal."""

    if not isinstance(seal, Mapping):
        raise PublishSealError("prepublication seal must be an object")
    if seal.get("schema") != SEAL_SCHEMA:
        raise PublishSealError("prepublication seal schema mismatch")
    if seal.get("task_id") != "OUL-043":
        raise PublishSealError("prepublication seal is not the OUL-043 document")
    if seal.get("publication_authorized") is not True:
        raise PublishSealError("prepublication seal does not authorize public mutation")
    if seal.get("authorizing_for_publication") is not True:
        raise PublishSealError("prepublication seal is not authorizing for publication")
    if seal.get("created_before_mutation") is not True:
        raise PublishSealError("prepublication seal must be created before mutation")
    if seal.get("timing") != SEAL_TIMING or seal.get("seal_timing") != SEAL_TIMING:
        raise PublishSealError("prepublication seal timing must be before_mutation")
    if seal.get("created_after_mutation") is True or seal.get("post_hoc") is True:
        raise PublishSealError("public mutation refuses a post-hoc prepublication seal")
    if seal.get("future") is True or seal.get("sealed_in_future") is True:
        raise PublishSealError("public mutation refuses a future-dated prepublication seal")
    if seal.get("present") is False:
        raise PublishSealError("prepublication seal is absent")
    if (seal.get("closure") or {}).get("generated_work_blocks_publication") is True:
        raise PublishSealError("generated work still blocks publication")
    _verify_receipt_digest(seal, digest_key="seal_sha256")
    manifest = normalize_sha256(
        str(seal.get("manifest_digest") or seal.get("final_manifest_digest") or ""),
        name="seal.manifest",
    )
    if expected_manifest is not None and manifest != expected_manifest:
        raise PublishSealError(
            "prepublication seal manifest digest drifted from the publish plan"
        )
    expires_at = str(seal.get("expires_at") or (seal.get("expiration") or {}).get("expires_at") or "")
    if not expires_at:
        raise PublishSealError("prepublication seal is missing expires_at")
    current = now if now is not None else datetime.now(timezone.utc)
    if current >= _parse_utc(expires_at):
        raise PublishSealError(
            f"prepublication seal expired at {expires_at}; reissue is required"
        )
    targets = dict(seal.get("target_ids") or {})
    if targets.get("dataset_repo_id") != AUTHORIZED_DATASET_REPO_ID:
        raise PublishSealError("seal target dataset is not authorized")
    if targets.get("source_bucket") != AUTHORIZED_BUCKET_ID:
        raise PublishSealError("seal target bucket is not authorized")
    prefix = str(seal.get("bucket_prefix") or "")
    if prefix != release_prefix_for(manifest):
        raise PublishSealError(
            "seal bucket prefix is not releases/<manifest_sha256>/ for this candidate"
        )
    reject_credentials_in_payload(seal, label="prepublication_seal")
    return as_gate_seal(seal)


def load_raw_root_snapshot(
    *,
    repo_root: Path | str | None = None,
) -> dict[str, str]:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    snapshot = load_json_mapping(root / BUCKET_SNAPSHOT_RELPATH)
    records = snapshot.get("canonical_records") or []
    objects: dict[str, str] = {}
    if not isinstance(records, list):
        raise MismatchError("bucket snapshot canonical_records must be a list")
    for item in records:
        if not isinstance(item, Mapping):
            continue
        path = str(item.get("path") or "").strip().lstrip("/")
        digest = str(item.get("xet_hash") or item.get("sha256") or "")
        if not path:
            continue
        if "/" not in path:
            objects[path] = digest
    if not objects:
        raise MismatchError("bucket snapshot contains no raw-root objects")
    return objects


def staged_artifacts(staging: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the exact staged bytes recorded by OUL-041."""

    artifacts: list[dict[str, Any]] = []
    for index, row in enumerate(staging.get("remote_objects") or []):
        if not isinstance(row, Mapping):
            raise MismatchError(f"staging remote_objects[{index}] must be an object")
        rel = str(row.get("relative_path") or "")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise PublishSafetyError(
                f"staging remote_objects[{index}] has unsafe relative_path: {rel!r}"
            )
        sha = normalize_sha256(str(row.get("sha256") or ""), name=f"staged.{rel}")
        cid = str(row.get("content_cid") or content_cid_for(sha))
        size = row.get("size_bytes")
        dataset_obj = dict(row.get("dataset_object") or {})
        bucket_obj = dict(row.get("bucket_object") or {})
        if not dataset_obj.get("object_id") or not bucket_obj.get("object_id"):
            raise MismatchError(
                f"staging remote_objects[{index}] is missing object identity"
            )
        if dataset_obj.get("sha256") != sha or bucket_obj.get("sha256") != sha:
            raise MismatchError(
                f"staging remote_objects[{index}] dataset/bucket digest drifted"
            )
        artifacts.append(
            {
                "content_cid": cid,
                "operation": "add_only_upload",
                "relative_path": rel,
                "sha256": sha,
                "size_bytes": size if isinstance(size, int) else None,
                "staging_bucket_object_id": bucket_obj.get("object_id"),
                "staging_dataset_object_id": dataset_obj.get("object_id"),
            }
        )
    if not artifacts:
        raise MismatchError("staging produced no publishable artifacts")
    return artifacts


def bind_exact_staged_bytes(
    *,
    candidate: Mapping[str, Any],
    staging: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
) -> None:
    inventory = dict((candidate.get("artifact_digests") or {}).get("inventory") or {})
    uploaded = {item["relative_path"]: item["sha256"] for item in artifacts}
    if not inventory:
        raise MismatchError("candidate inventory is empty")
    missing = [path for path in inventory if path not in uploaded]
    if missing:
        raise MismatchError(
            "staged bytes are missing candidate artifacts: " + ", ".join(missing[:8])
        )
    for path, digest in inventory.items():
        expected = normalize_sha256(str(digest), name=f"candidate.{path}")
        if uploaded[path] != expected:
            raise MismatchError(
                f"staged digest for {path} drifted from the candidate inventory"
            )
    staging_manifest = normalize_sha256(
        str(staging.get("manifest_digest") or ""), name="staging.manifest"
    )
    candidate_manifest = normalize_sha256(
        str((candidate.get("candidate") or {}).get("manifest_digest") or ""),
        name="candidate.manifest",
    )
    if staging_manifest != candidate_manifest:
        raise MismatchError("staging manifest digest drifted from the candidate")


# ---------------------------------------------------------------------------
# Plan construction
# ---------------------------------------------------------------------------


def build_pointer_document(
    *,
    manifest_digest: str,
    dataset_revision: str,
    bucket_prefix: str,
    release_root_cid: str,
) -> dict[str, Any]:
    pointer = {
        "bucket_prefix": bucket_prefix,
        "dataset_repo_id": AUTHORIZED_DATASET_REPO_ID,
        "dataset_revision": dataset_revision,
        "kind": "open-us-law-release-pointer",
        "manifest_sha256": manifest_digest,
        "release_root_cid": release_root_cid,
        "schema": POINTER_SCHEMA,
        "source_bucket": AUTHORIZED_BUCKET_ID,
    }
    reject_credentials_in_payload(pointer, label="release_pointer")
    reject_identity_contamination(pointer, label="release_pointer")
    encoded = json.dumps(
        pointer, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    if len(encoded) > MAX_POINTER_BYTES:
        raise PublishSafetyError(
            f"pointer document is not tiny ({len(encoded)} > {MAX_POINTER_BYTES})"
        )
    digest = hashlib.sha256(encoded).hexdigest()
    return {
        "bytes": encoded,
        "document": pointer,
        "sha256": digest,
        "size_bytes": len(encoded),
    }


def build_publish_plan(
    *,
    seal: Mapping[str, Any],
    staging: Mapping[str, Any],
    candidate: Mapping[str, Any],
    dry_run: bool = True,
) -> dict[str, Any]:
    """Build a deterministic additive public-release plan."""

    if type(dry_run) is not bool:
        raise PublishOpenUsLawError("dry_run must be boolean")
    gate_seal = revalidate_prepublication_seal(
        seal,
        expected_manifest=normalize_sha256(
            str(staging.get("manifest_digest") or ""), name="staging.manifest"
        ),
    )
    artifacts = staged_artifacts(staging)
    bind_exact_staged_bytes(
        candidate=candidate, staging=staging, artifacts=artifacts
    )
    manifest_digest = normalize_sha256(
        str(seal.get("manifest_digest") or ""), name="seal.manifest"
    )
    prefix = release_prefix_for(manifest_digest)
    if str(seal.get("bucket_prefix") or "") != prefix:
        raise PublishSealError("seal bucket prefix drifted from releases/<manifest_sha256>/")
    if str(staging.get("bucket_staging_prefix") or "") != prefix:
        raise MismatchError("staging prefix is not the content-addressed release prefix")
    dataset_id = _normalize_dataset_id(
        str(staging.get("target_repo") or staging.get("dataset_id") or DEFAULT_DATASET_REPO),
        label="target_repo",
    )
    if dataset_id != AUTHORIZED_DATASET_REPO_ID:
        raise PublishSafetyError(
            f"dataset target {dataset_id!r} is not the authorized Dataset"
        )
    bucket = _normalize_dataset_id(
        str(staging.get("bucket_id") or DEFAULT_BUCKET_ID), label="bucket_id"
    )
    if bucket != AUTHORIZED_BUCKET_ID:
        raise PublishSafetyError(f"bucket target {bucket!r} is not the authorized Bucket")
    staging_revision = require_immutable_revision(
        str(staging.get("dataset_revision") or ""), name="staging.dataset_revision"
    )
    release_root_cid = str(
        (candidate.get("candidate") or {}).get("release_root_cid")
        or f"sha256:{manifest_digest}"
    )
    operations = (
        "dataset_create",
        "dataset_additive_commit",
        "bucket_release_prefix_write",
        "bucket_pointer_update_last",
    )
    _assert_operations_authorized(operations)
    upload_bytes = sum(
        int(item["size_bytes"])
        for item in artifacts
        if isinstance(item["size_bytes"], int)
    )
    binding = {
        "artifacts": [
            {
                "content_cid": item["content_cid"],
                "operation": item["operation"],
                "relative_path": item["relative_path"],
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"],
            }
            for item in artifacts
        ],
        "bucket_id": bucket,
        "bucket_release_prefix": prefix,
        "dataset_id": dataset_id,
        "deletion_occurred": False,
        "legacy_files_deleted": False,
        "manifest_digest": manifest_digest,
        "pointer_updated_last": True,
        "release_root_cid": release_root_cid,
        "schema": PUBLISH_PLAN_SCHEMA,
        "seal_sha256": seal.get("seal_sha256"),
        "staging_receipt_sha256": staging.get("receipt_sha256"),
        "staging_revision": staging_revision,
        "target_repo": dataset_id,
    }
    plan_digest = digest_mapping(binding)
    dataset_revision = derive_public_dataset_revision(
        manifest_digest=manifest_digest,
        plan_digest=plan_digest,
        staging_revision=staging_revision,
    )
    if dataset_revision == staging_revision:
        raise PublishSafetyError(
            "public dataset revision must be a new additive commit, not the staging pin"
        )
    pointer = build_pointer_document(
        manifest_digest=manifest_digest,
        dataset_revision=dataset_revision,
        bucket_prefix=prefix,
        release_root_cid=release_root_cid,
    )
    plan: dict[str, Any] = {
        "acceptance": {
            "additive_only": True,
            "credentials_environment_only": True,
            "deletion_impossible": True,
            "exact_staged_bytes": True,
            "force_push_impossible": True,
            "immediate_gate_revalidation_required": True,
            "pointer_updated_last": True,
            "prepublication_seal_required": True,
            "raw_root_write_impossible": True,
            "tiny_pointer": pointer["size_bytes"] <= MAX_POINTER_BYTES,
            "visibility_change_impossible": True,
        },
        "artifacts": artifacts,
        "bucket_id": bucket,
        "bucket_pointer_path": BUCKET_POINTER_PATH,
        "bucket_release_prefix": prefix,
        "candidate_receipt_sha256": candidate.get("receipt_sha256"),
        "dataset_id": dataset_id,
        "dataset_revision": dataset_revision,
        "dry_run": dry_run,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "gate_seal": gate_seal,
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "manifest_digest": manifest_digest,
        "operations": list(operations),
        "plan_digest": plan_digest,
        "pointer": pointer["document"],
        "pointer_sha256": pointer["sha256"],
        "pointer_size_bytes": pointer["size_bytes"],
        "pointer_updated_last": True,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "release_root_cid": release_root_cid,
        "schema": PUBLISH_PLAN_SCHEMA,
        "seal_sha256": seal.get("seal_sha256"),
        "source_revision": (candidate.get("candidate") or {}).get("source_revision"),
        "staging_receipt_sha256": staging.get("receipt_sha256"),
        "staging_revision": staging_revision,
        "task_id": TASK_ID,
        "target_repo": dataset_id,
        "upload_bytes": upload_bytes,
        "upload_file_count": len(artifacts),
        "visibility": "public",
        "visibility_change_allowed": False,
    }
    reject_credentials_in_payload(plan, label="publish_plan")
    reject_identity_contamination(plan, label="publish_plan")
    assert_safe_publish_plan(plan)
    return plan


def assert_safe_publish_plan(plan: Mapping[str, Any]) -> None:
    if not isinstance(plan, Mapping):
        raise PublishOpenUsLawError("publish plan must be an object")
    required = (
        "target_repo",
        "dataset_revision",
        "bucket_release_prefix",
        "manifest_digest",
        "plan_digest",
        "release_root_cid",
        "operations",
        "artifacts",
        "gate_seal",
        "pointer",
        "seal_sha256",
    )
    missing = [key for key in required if not plan.get(key)]
    if missing:
        raise PublishOpenUsLawError(
            "publish plan missing explicit fields: " + ", ".join(missing)
        )
    _normalize_dataset_id(str(plan["target_repo"]), label="target_repo")
    if str(plan["target_repo"]) != AUTHORIZED_DATASET_REPO_ID:
        raise PublishSafetyError("plan target_repo is not the authorized Dataset")
    if str(plan["bucket_id"]) != AUTHORIZED_BUCKET_ID:
        raise PublishSafetyError("plan bucket_id is not the authorized Bucket")
    revision = require_immutable_revision(
        str(plan["dataset_revision"]), name="dataset_revision"
    )
    if revision == str(plan.get("staging_revision") or ""):
        raise PublishSafetyError("public revision must differ from the staging pin")
    prefix = str(plan["bucket_release_prefix"])
    expected_prefix = release_prefix_for(str(plan["manifest_digest"]))
    if prefix != expected_prefix:
        raise PublishSafetyError(
            "bucket release prefix must be the unique content-addressed "
            f"{BUCKET_RELEASE_PREFIX_TEMPLATE} for this candidate"
        )
    if plan.get("legacy_files_deleted") is not False:
        raise PublishSafetyError("publish plan must declare legacy_files_deleted=false")
    if plan.get("visibility_change_allowed") is not False:
        raise PublishSafetyError("visibility_change_allowed must be false")
    if plan.get("pointer_updated_last") is not True:
        raise PublishSafetyError("publish plan must update the pointer last")
    if str(plan.get("visibility") or "").casefold() != "public":
        raise PublishSafetyError("publication visibility must remain public")
    if int(plan.get("pointer_size_bytes") or 0) > MAX_POINTER_BYTES:
        raise PublishSafetyError("pointer is not tiny")
    ops = plan.get("operations") or []
    if not isinstance(ops, list):
        raise PublishOpenUsLawError("operations must be a list")
    _assert_operations_authorized([str(item) for item in ops])
    if "bucket_pointer_update_last" not in ops:
        raise PublishSafetyError("publish plan must include the last pointer update")
    if list(ops)[-1] != "bucket_pointer_update_last":
        raise PublishSafetyError("bucket_pointer_update_last must be the last operation")
    artifacts = plan.get("artifacts") or []
    if not isinstance(artifacts, list) or not artifacts:
        raise PublishOpenUsLawError("publish plan requires a non-empty artifacts list")
    for index, item in enumerate(artifacts):
        if not isinstance(item, Mapping):
            raise PublishOpenUsLawError(f"artifacts[{index}] must be an object")
        op = str(item.get("operation") or "").casefold()
        if op != "add_only_upload":
            raise PublishSafetyError(
                f"artifacts[{index}] operation must be add_only_upload, got {op!r}"
            )
        rel = str(item.get("relative_path") or "")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise PublishSafetyError(
                f"artifacts[{index}] has unsafe relative_path: {rel!r}"
            )
        digest = str(item.get("sha256") or "").casefold()
        if not _SHA256_RE.fullmatch(digest):
            raise PublishOpenUsLawError(
                f"artifacts[{index}] requires a full sha256 digest"
            )
    reject_credentials_in_payload(plan, label="publish_plan")


# ---------------------------------------------------------------------------
# Publication-gate requests + immediate revalidation
# ---------------------------------------------------------------------------


def _base_gate_request(
    plan: Mapping[str, Any],
    *,
    operation: str,
    credentials_scope: str,
    credential_identity: str,
    object_path: str | None = None,
    prefix_complete: bool = False,
    prefix_redownload_verified: bool = False,
    pointer_updated_last: bool = False,
) -> dict[str, Any]:
    request: dict[str, Any] = {
        "phase": PublicationPhase.PUBLIC.value,
        "operation": operation,
        "dataset_repo_id": str(plan["target_repo"]),
        "bucket_id": str(plan["bucket_id"]),
        "final_manifest_digest": plan["manifest_digest"],
        "authorize_mutation": True,
        "sealed": True,
        "overwrite_raw_root": False,
        "overwrite_existing_prefix": False,
        "delete_requested": False,
        "force_push": False,
        "history_rewrite": False,
        "visibility_change": False,
        "visibility": "public",
        "prefix_complete": prefix_complete,
        "prefix_redownload_verified": prefix_redownload_verified,
        "pointer_updated_last": pointer_updated_last,
        "credentials_environment_only": True,
        "secret_redacted": True,
        "credentials_scope": credentials_scope,
        "credential_identity": credential_identity,
        "prepublication_seal": dict(plan["gate_seal"]),
        "payload": {
            "release_mode": "additive",
            "credentials_environment_only": True,
            "secret_redacted": True,
            "bucket_release_prefix": plan["bucket_release_prefix"],
            "dataset_revision": plan["dataset_revision"],
        },
        "argv": [
            "publish-open-us-law",
            "--phase",
            "public",
            "--authorize-mutation",
        ],
    }
    if object_path is not None:
        request["object_path"] = object_path
    return request


def dataset_create_request(plan: Mapping[str, Any]) -> dict[str, Any]:
    repo = str(plan["target_repo"])
    return _base_gate_request(
        plan,
        operation="dataset_create",
        credentials_scope=credentials_scope_for(dataset_repo_id=repo),
        credential_identity=f"env:{repo}",
    )


def dataset_commit_request(plan: Mapping[str, Any]) -> dict[str, Any]:
    repo = str(plan["target_repo"])
    return _base_gate_request(
        plan,
        operation="dataset_additive_commit",
        credentials_scope=credentials_scope_for(dataset_repo_id=repo),
        credential_identity=f"env:{repo}",
    )


def bucket_prefix_request(plan: Mapping[str, Any], object_path: str) -> dict[str, Any]:
    bucket = str(plan["bucket_id"])
    return _base_gate_request(
        plan,
        operation="bucket_release_prefix_write",
        credentials_scope=credentials_scope_for(bucket_id=bucket),
        credential_identity=f"env:{bucket}",
        object_path=object_path,
    )


def pointer_update_request(plan: Mapping[str, Any]) -> dict[str, Any]:
    bucket = str(plan["bucket_id"])
    return _base_gate_request(
        plan,
        operation="bucket_pointer_update_last",
        credentials_scope=credentials_scope_for(bucket_id=bucket),
        credential_identity=f"env:{bucket}",
        object_path=BUCKET_POINTER_PATH,
        prefix_complete=True,
        prefix_redownload_verified=True,
        pointer_updated_last=True,
    )


def revalidate_gate_and_mutate(
    plan: Mapping[str, Any],
    request: Mapping[str, Any],
    callback: Callable[[Any], T],
    *,
    seal: Mapping[str, Any],
    now: datetime | None = None,
) -> tuple[dict[str, Any], T]:
    """Revalidate the seal, then run the gate immediately before *callback*."""

    gate_seal = revalidate_prepublication_seal(
        seal,
        expected_manifest=str(plan["manifest_digest"]),
        now=now,
    )
    live_request = dict(request)
    live_request["prepublication_seal"] = gate_seal
    result = authorize_and_mutate(live_request, callback)
    summary = {
        "authorized": True,
        "network_mutation_permitted": True,
        "object_path": live_request.get("object_path"),
        "operation": live_request["operation"],
        "phase": PublicationPhase.PUBLIC.value,
        "pointer_updated_last": bool(live_request.get("pointer_updated_last")),
        "prefix_complete": bool(live_request.get("prefix_complete")),
        "prefix_redownload_verified": bool(
            live_request.get("prefix_redownload_verified")
        ),
        "revalidated": True,
        "seal_sha256": seal.get("seal_sha256"),
    }
    return summary, result


# ---------------------------------------------------------------------------
# Plan apply
# ---------------------------------------------------------------------------


def apply_publish_plan(
    plan: Mapping[str, Any],
    *,
    seal: Mapping[str, Any],
    reviewed_plan_digest: str,
    store: IsolatedPublicReleaseStore | None = None,
    raw_root_objects: Mapping[str, str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Commit exact staged bytes after immediate gate revalidation."""

    assert_safe_publish_plan(plan)
    expected = str(plan["plan_digest"])
    reviewed = normalize_sha256(reviewed_plan_digest, name="reviewed_plan_digest")
    if reviewed != expected:
        raise PublishPlanReviewError(
            "apply refused: reviewed dry-run plan digest does not match the "
            f"current plan ({reviewed} != {expected})"
        )

    isolated = store or IsolatedPublicReleaseStore(raw_root_objects)
    revalidations: list[dict[str, Any]] = []
    prefix = str(plan["bucket_release_prefix"])
    revision = str(plan["dataset_revision"])
    repo = str(plan["target_repo"])
    bucket = str(plan["bucket_id"])

    def _record(summary: Mapping[str, Any]) -> None:
        row = dict(summary)
        row["sequence"] = len(revalidations) + 1
        revalidations.append(row)

    created, _unused = revalidate_gate_and_mutate(
        plan,
        dataset_create_request(plan),
        lambda _decision: isolated.create_dataset(repo_id=repo),
        seal=seal,
        now=now,
    )
    _record(created)

    remote_objects: list[dict[str, Any]] = []

    def _commit_dataset(_decision: Any) -> list[dict[str, Any]]:
        committed: list[dict[str, Any]] = []
        for item in plan["artifacts"]:
            committed.append(
                isolated.add_dataset(
                    repo_id=repo,
                    revision=revision,
                    path=str(item["relative_path"]),
                    sha256=str(item["sha256"]),
                    size_bytes=item["size_bytes"]
                    if isinstance(item["size_bytes"], int)
                    else None,
                    content_cid=str(item["content_cid"]),
                )
            )
        return committed

    commit_summary, dataset_records = revalidate_gate_and_mutate(
        plan,
        dataset_commit_request(plan),
        _commit_dataset,
        seal=seal,
        now=now,
    )
    _record(commit_summary)

    bucket_records: list[dict[str, Any]] = []
    for item, dataset_record in zip(plan["artifacts"], dataset_records):
        rel = str(item["relative_path"])
        bucket_path = f"{prefix}{rel}"

        def _write_bucket(
            _decision: Any,
            *,
            _item: Mapping[str, Any] = item,
            _bucket_path: str = bucket_path,
        ) -> dict[str, Any]:
            return isolated.add_bucket(
                bucket_id=bucket,
                path=_bucket_path,
                sha256=str(_item["sha256"]),
                size_bytes=_item["size_bytes"]
                if isinstance(_item["size_bytes"], int)
                else None,
                content_cid=str(_item["content_cid"]),
            )

        bucket_summary, bucket_record = revalidate_gate_and_mutate(
            plan,
            bucket_prefix_request(plan, bucket_path),
            _write_bucket,
            seal=seal,
            now=now,
        )
        _record(bucket_summary)
        bucket_records.append(bucket_record)
        remote_objects.append(
            {
                "bucket_object": bucket_record,
                "content_cid": item["content_cid"],
                "dataset_object": dataset_record,
                "operation": "add_only_upload",
                "relative_path": rel,
                "sha256": item["sha256"],
                "size_bytes": item["size_bytes"]
                if isinstance(item["size_bytes"], int)
                else None,
                "staging_bucket_object_id": item.get("staging_bucket_object_id"),
                "staging_dataset_object_id": item.get("staging_dataset_object_id"),
            }
        )

    expected_bucket_paths = [f"{prefix}{item['relative_path']}" for item in plan["artifacts"]]
    isolated.mark_prefix_complete(expected_paths=expected_bucket_paths)
    redownload = isolated.redownload_verify_prefix(
        expected=[
            {
                "bucket_id": bucket,
                "path": f"{prefix}{item['relative_path']}",
                "sha256": item["sha256"],
            }
            for item in plan["artifacts"]
        ]
    )

    pointer_bytes = json.dumps(
        dict(plan["pointer"]),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    pointer_sha = hashlib.sha256(pointer_bytes).hexdigest()
    if pointer_sha != plan["pointer_sha256"]:
        raise MismatchError("pointer digest drifted from the reviewed plan")

    def _write_pointer(_decision: Any) -> dict[str, Any]:
        return isolated.update_pointer(
            bucket_id=bucket,
            pointer=dict(plan["pointer"]),
            sha256=pointer_sha,
            size_bytes=len(pointer_bytes),
            content_cid=content_cid_for(pointer_sha),
        )

    pointer_summary, pointer_record = revalidate_gate_and_mutate(
        plan,
        pointer_update_request(plan),
        _write_pointer,
        seal=seal,
        now=now,
    )
    _record(pointer_summary)

    if not isolated.raw_root_untouched():
        raise PublishSafetyError("raw bucket-root objects were mutated during publication")
    if isolated.deletion_occurred:
        raise PublishSafetyError("deletion occurred during publication")
    if not isolated.pointer_is_last():
        raise PublishSafetyError("pointer was not the last mutation")
    if not isolated.prefix_redownload_verified:
        raise PublishSafetyError("prefix redownload was not verified")
    if any(is_protected_raw_root_path(path) for (_bucket, path) in isolated.bucket if path != BUCKET_POINTER_PATH):
        raise PublishSafetyError("a protected raw-root path was written")

    identities_digest = digest_mapping(
        {
            "bucket_objects": [
                row["bucket_object"]["object_id"] for row in remote_objects
            ],
            "dataset_objects": [
                row["dataset_object"]["object_id"] for row in remote_objects
            ],
            "dataset_revision": revision,
            "manifest_digest": plan["manifest_digest"],
            "pointer_object_id": pointer_record["object_id"],
            "prefix": prefix,
        }
    )
    return {
        "dataset_created": True,
        "dataset_revision": revision,
        "deletion_occurred": False,
        "gate_revalidation_count": len(revalidations),
        "gate_revalidations": revalidations,
        "identities_digest": identities_digest,
        "pointer": dict(plan["pointer"]),
        "pointer_object": pointer_record,
        "pointer_sha256": pointer_sha,
        "pointer_size_bytes": len(pointer_bytes),
        "pointer_updated": True,
        "pointer_updated_last": True,
        "prefix_complete": True,
        "prefix_redownload_verified": True,
        "raw_root_paths": list(isolated.raw_root_paths()),
        "raw_root_untouched": True,
        "redownload": {
            "object_count": redownload["object_count"],
            "prefix_redownload_verified": True,
        },
        "remote_object_count": len(remote_objects) * 2 + 1,
        "remote_objects": remote_objects,
        "root_raw_object_overwritten": False,
        "store": isolated,
    }


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


def _acceptance_from_apply(
    plan: Mapping[str, Any],
    applied: Mapping[str, Any],
    *,
    reviewed: bool,
) -> dict[str, Any]:
    remote = list(applied.get("remote_objects") or [])
    identities_ok = bool(remote) and all(
        row.get("dataset_object", {}).get("object_id")
        and row.get("bucket_object", {}).get("object_id")
        and row.get("sha256")
        == next(
            (
                art["sha256"]
                for art in plan["artifacts"]
                if art["relative_path"] == row.get("relative_path")
            ),
            None,
        )
        for row in remote
    )
    revalidations = list(applied.get("gate_revalidations") or [])
    pointer_last = bool(revalidations) and revalidations[-1].get(
        "operation"
    ) == "bucket_pointer_update_last" and all(
        row.get("operation") != "bucket_pointer_update_last"
        for row in revalidations[:-1]
    ) and all(row.get("revalidated") is True for row in revalidations)
    prefix = str(plan.get("bucket_release_prefix") or "")
    expected_count = len(plan["artifacts"]) * 2 + 1
    acceptance = {
        "additive_bucket_prefix_copy": prefix == release_prefix_for(
            str(plan["manifest_digest"])
        )
        and all(
            str((row.get("bucket_object") or {}).get("path") or "").startswith(prefix)
            for row in remote
        ),
        "additive_dataset_commit": all(
            (row.get("dataset_object") or {}).get("repo_id")
            == AUTHORIZED_DATASET_REPO_ID
            and (row.get("dataset_object") or {}).get("revision")
            == applied.get("dataset_revision")
            for row in remote
        ),
        "all_expected_outputs_required": True,
        "bucket_prefix_is_releases_manifest_sha256": prefix
        == f"releases/{plan['manifest_digest']}/",
        "criteria": ACCEPTANCE_CRITERIA,
        "exact_staged_bytes_committed": identities_ok
        and int(applied.get("remote_object_count") or 0) == expected_count,
        "immediate_gate_revalidation_before_each_callback": pointer_last
        and int(applied.get("gate_revalidation_count") or 0) == len(revalidations)
        and len(revalidations) == len(plan["artifacts"]) + 3,
        "no_deletion": applied.get("deletion_occurred") is False,
        "no_root_raw_object_overwritten": applied.get("raw_root_untouched") is True
        and applied.get("root_raw_object_overwritten") is False,
        "no_secret_or_path_leak": True,
        "pointer_updated_last": applied.get("pointer_updated_last") is True
        and pointer_last
        and applied.get("prefix_redownload_verified") is True,
        "reviewed_dry_run_plan": bool(reviewed)
        and bool(plan.get("plan_digest"))
        and bool(_SHA256_RE.fullmatch(str(plan.get("plan_digest") or ""))),
    }
    failed = [
        key for key, value in acceptance.items() if key != "criteria" and not value
    ]
    if failed:
        raise MismatchError("publication-receipt acceptance failed: " + ", ".join(failed))
    return acceptance


def build_publication_receipt(
    plan: Mapping[str, Any],
    applied: Mapping[str, Any],
    *,
    seal: Mapping[str, Any],
    staging: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the sealed isolated public-publication receipt."""

    assert_safe_publish_plan(plan)
    acceptance = _acceptance_from_apply(plan, applied, reviewed=True)
    remote_objects = list(applied["remote_objects"])
    receipt: dict[str, Any] = {
        "acceptance": acceptance,
        "adr_path": ADR_PATH,
        "authorized_bucket": AUTHORIZED_BUCKET_ID,
        "authorized_dataset": AUTHORIZED_DATASET_REPO_ID,
        "authorized_operations": sorted(AUTHORIZED_OPERATIONS),
        "board_namespace": BOARD_NAMESPACE,
        "bucket_id": plan["bucket_id"],
        "bucket_pointer_path": BUCKET_POINTER_PATH,
        "bucket_pointer_updated": True,
        "bucket_release_prefix": plan["bucket_release_prefix"],
        "bundle": BUNDLE,
        "candidate": {
            "dataset_id": (candidate.get("candidate") or {}).get("dataset_id"),
            "kind": (candidate.get("candidate") or {}).get("kind"),
            "manifest_digest": plan["manifest_digest"],
            "receipt_sha256": candidate.get("receipt_sha256"),
            "release_root_cid": plan["release_root_cid"],
            "source_revision": (candidate.get("candidate") or {}).get(
                "source_revision"
            ),
        },
        "code_version": CODE_VERSION,
        "dataset_created": True,
        "dataset_id": plan["dataset_id"],
        "dataset_revision": applied["dataset_revision"],
        "deletion_occurred": False,
        "depends_on": list(DEPENDS_ON),
        "dry_run": False,
        "fixture_id": FIXTURE_ID,
        "gate_revalidation_count": applied["gate_revalidation_count"],
        "gate_revalidations": applied["gate_revalidations"],
        "goal_id": GOAL_ID,
        "identities_digest": applied["identities_digest"],
        "isolated_transport": True,
        "live_network": False,
        "manifest_digest": plan["manifest_digest"],
        "mutation_authorized": True,
        "mutation_executed": True,
        "network_required": False,
        "notes": (
            "Authorized public Dataset and content-addressed Bucket release "
            "(OUL-044). After immediate publication-gate revalidation of the "
            "OUL-043 prepublication seal, the exact staged bytes were "
            "committed additively to justicedao/open-us-law-sparse-graphrag "
            "and copied under releases/<manifest_sha256>/ in "
            "justicedao/open-us-law-bucket. The tiny LATEST.json pointer was "
            "updated last after prefix redownload verification. No root raw "
            "object was overwritten and no deletion occurred. Live Hub "
            "contact is not required by this isolated receipt."
        ),
        "plan_digest": plan["plan_digest"],
        "pointer": applied["pointer"],
        "pointer_object": applied["pointer_object"],
        "pointer_sha256": applied["pointer_sha256"],
        "pointer_size_bytes": applied["pointer_size_bytes"],
        "pointer_updated": True,
        "pointer_updated_last": True,
        "prefix_complete": True,
        "prefix_redownload_verified": True,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_mutation_authorized": True,
        "public_mutation_executed": True,
        "publication_authorized": True,
        "raw_bucket_root_object_count": len(applied.get("raw_root_paths") or []),
        "raw_bucket_root_untouched": True,
        "remote_default_branches_mutated": False,
        "remote_object_count": applied["remote_object_count"],
        "remote_objects": remote_objects,
        "remote_write_contacted": False,
        "reviewed_plan_digest": plan["plan_digest"],
        "root_raw_object_overwritten": False,
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "seal": {
            "expires_at": seal.get("expires_at"),
            "manifest_digest": seal.get("manifest_digest"),
            "seal_sha256": seal.get("seal_sha256"),
            "staging_revision": seal.get("staging_revision"),
            "task_id": seal.get("task_id"),
            "timing": seal.get("timing"),
        },
        "seal_sha256": seal.get("seal_sha256"),
        "staging_receipt_sha256": staging.get("receipt_sha256"),
        "staging_revision": plan["staging_revision"],
        "status": "published_isolated",
        "task_id": TASK_ID,
        "target_repo": plan["target_repo"],
        "tokens_used": False,
        "transport": "isolated_recorded_public_store",
        "upload_bytes": plan["upload_bytes"],
        "upload_file_count": plan["upload_file_count"],
        "visibility_changed": False,
    }
    receipt["receipt_sha256"] = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    reject_credentials_in_payload(receipt, label="publication_receipt")
    reject_path_leaks(receipt, label="publication_receipt")
    reject_identity_contamination(receipt, label="publication_receipt")
    return receipt


def build_dry_run_receipt(plan: Mapping[str, Any]) -> dict[str, Any]:
    assert_safe_publish_plan(plan)
    receipt: dict[str, Any] = {
        "bucket_release_prefix": plan["bucket_release_prefix"],
        "dataset_revision": plan["dataset_revision"],
        "dry_run": True,
        "goal_id": GOAL_ID,
        "human_approval_required": True,
        "live_network": False,
        "manifest_digest": plan["manifest_digest"],
        "mutation_authorized": False,
        "mutation_executed": False,
        "plan_digest": plan["plan_digest"],
        "pointer_updated": False,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "remote_write_contacted": False,
        "schema": PUBLISH_PLAN_SCHEMA,
        "seal_sha256": plan["seal_sha256"],
        "status": "dry_run_reviewed",
        "task_id": TASK_ID,
        "target_repo": plan["target_repo"],
        "tokens_used": False,
        "upload_bytes": plan["upload_bytes"],
        "upload_file_count": plan["upload_file_count"],
    }
    reject_credentials_in_payload(receipt, label="dry_run_receipt")
    reject_identity_contamination(receipt, label="dry_run_receipt")
    return receipt


def build_default_publication_receipt(
    *,
    repo_root: Path | str | None = None,
    seal_path: Path | str | None = None,
    staging_path: Path | str | None = None,
    candidate_path: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    seal = load_prepublication_seal(seal_path, repo_root=repo_root, now=now)
    staging = load_staging_receipt(staging_path, repo_root=repo_root)
    candidate = load_candidate_receipt(candidate_path, repo_root=repo_root)
    plan = build_publish_plan(
        seal=seal, staging=staging, candidate=candidate, dry_run=False
    )
    raw_root = load_raw_root_snapshot(repo_root=repo_root)
    applied = apply_publish_plan(
        plan,
        seal=seal,
        reviewed_plan_digest=str(plan["plan_digest"]),
        raw_root_objects=raw_root,
        now=now,
    )
    return build_publication_receipt(
        plan, applied, seal=seal, staging=staging, candidate=candidate
    )


def materialize_default_receipt(
    *,
    repo_root: Path | str | None = None,
    receipt_path: Path | str | None = None,
    seal_path: Path | str | None = None,
    staging_path: Path | str | None = None,
    candidate_path: Path | str | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], Path]:
    receipt = build_default_publication_receipt(
        repo_root=repo_root,
        seal_path=seal_path,
        staging_path=staging_path,
        candidate_path=candidate_path,
        now=now,
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
        "plan_digest",
        "dataset_revision",
        "bucket_release_prefix",
        "receipt_sha256",
        "status",
        "live_network",
        "publication_authorized",
        "raw_bucket_root_untouched",
        "pointer_updated",
        "pointer_updated_last",
        "deletion_occurred",
        "root_raw_object_overwritten",
        "remote_object_count",
        "identities_digest",
        "pointer_sha256",
        "seal_sha256",
    )
    mismatches.extend(_compare_mappings(fresh, sealed, path="receipt", keys=top_keys))
    mismatches.extend(
        _compare_mappings(
            dict(fresh.get("candidate") or {}),
            dict(sealed.get("candidate") or {}),
            path="candidate",
            keys=(
                "manifest_digest",
                "receipt_sha256",
                "release_root_cid",
                "dataset_id",
            ),
        )
    )
    if fresh.get("acceptance") != sealed.get("acceptance"):
        mismatches.append("acceptance drifted from the sealed receipt")
    if fresh.get("pointer") != sealed.get("pointer"):
        mismatches.append("pointer drifted from the sealed receipt")
    fresh_ids = [
        (
            row.get("relative_path"),
            row.get("sha256"),
            (row.get("dataset_object") or {}).get("object_id"),
            (row.get("bucket_object") or {}).get("object_id"),
        )
        for row in (fresh.get("remote_objects") or [])
        if isinstance(row, Mapping)
    ]
    sealed_ids = [
        (
            row.get("relative_path"),
            row.get("sha256"),
            (row.get("dataset_object") or {}).get("object_id"),
            (row.get("bucket_object") or {}).get("object_id"),
        )
        for row in (sealed.get("remote_objects") or [])
        if isinstance(row, Mapping)
    ]
    if fresh_ids != sealed_ids:
        mismatches.append("remote object identities drifted from the sealed receipt")
    if (fresh.get("pointer_object") or {}).get("object_id") != (
        sealed.get("pointer_object") or {}
    ).get("object_id"):
        mismatches.append("pointer object identity drifted from the sealed receipt")
    return mismatches


def check_receipt_structure(receipt: Mapping[str, Any]) -> None:
    required = (
        "acceptance",
        "bucket_release_prefix",
        "candidate",
        "dataset_revision",
        "identities_digest",
        "manifest_digest",
        "plan_digest",
        "pointer",
        "pointer_object",
        "receipt_sha256",
        "remote_objects",
        "reviewed_plan_digest",
        "seal_sha256",
        "gate_revalidations",
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
    if receipt.get("publication_authorized") is not True:
        raise MismatchError("receipt must authorize the bound public mutation")
    if receipt.get("public_mutation_authorized") is not True:
        raise MismatchError("receipt must authorize the bound public mutation")
    if receipt.get("live_network") is not False:
        raise MismatchError("receipt must be network-free")
    if receipt.get("network_required") is not False:
        raise MismatchError("receipt must be network-free")
    if receipt.get("dry_run") is not False:
        raise MismatchError("sealed receipt must record the applied isolated upload")
    if receipt.get("mutation_executed") is not True:
        raise MismatchError("sealed receipt must record the isolated apply")
    if receipt.get("raw_bucket_root_untouched") is not True:
        raise MismatchError("receipt does not prove raw bucket root was untouched")
    if receipt.get("root_raw_object_overwritten") is not False:
        raise MismatchError("receipt must not overwrite a root raw object")
    if receipt.get("deletion_occurred") is not False:
        raise MismatchError("receipt must prove no deletion occurred")
    if receipt.get("pointer_updated") is not True:
        raise MismatchError("receipt must update LATEST.json")
    if receipt.get("pointer_updated_last") is not True:
        raise MismatchError("receipt must update the pointer last")
    if receipt.get("prefix_redownload_verified") is not True:
        raise MismatchError("receipt must redownload-verify the release prefix")
    if receipt.get("reviewed_plan_digest") != receipt.get("plan_digest"):
        raise MismatchError("reviewed plan digest does not match plan_digest")
    revision = require_immutable_revision(
        str(receipt.get("dataset_revision")), name="receipt.dataset_revision"
    )
    if revision == str(receipt.get("staging_revision") or ""):
        raise MismatchError("public revision must differ from the staging pin")
    prefix = str(receipt.get("bucket_release_prefix") or "")
    expected_prefix = release_prefix_for(str(receipt.get("manifest_digest")))
    if prefix != expected_prefix:
        raise MismatchError("bucket release prefix is not unique to this candidate")
    if str(receipt.get("authorized_dataset") or "") != AUTHORIZED_DATASET_REPO_ID:
        raise MismatchError("receipt authorized_dataset drifted")
    if str(receipt.get("authorized_bucket") or "") != AUTHORIZED_BUCKET_ID:
        raise MismatchError("receipt authorized_bucket drifted")
    objects = receipt.get("remote_objects") or []
    if not isinstance(objects, list) or not objects:
        raise MismatchError("receipt is missing remote object identities")
    expected_count = len(objects) * 2 + 1
    if int(receipt.get("remote_object_count") or 0) != expected_count:
        raise MismatchError("remote_object_count does not match recorded identities")
    for index, row in enumerate(objects):
        if not isinstance(row, Mapping):
            raise MismatchError(f"remote_objects[{index}] must be an object")
        dataset_obj = row.get("dataset_object") or {}
        bucket_obj = row.get("bucket_object") or {}
        if not dataset_obj.get("object_id") or not bucket_obj.get("object_id"):
            raise MismatchError(f"remote_objects[{index}] missing object identity")
        if not str(bucket_obj.get("path") or "").startswith(prefix):
            raise MismatchError(
                f"remote_objects[{index}] is not under the unique release prefix"
            )
        if is_protected_raw_root_path(str(bucket_obj.get("path") or "")):
            raise MismatchError(
                f"remote_objects[{index}] targets a protected raw-root path"
            )
        if dataset_obj.get("repo_id") != AUTHORIZED_DATASET_REPO_ID:
            raise MismatchError(
                f"remote_objects[{index}] is not the authorized Dataset"
            )
    pointer_obj = dict(receipt.get("pointer_object") or {})
    if pointer_obj.get("path") != BUCKET_POINTER_PATH:
        raise MismatchError("pointer object path must be LATEST.json")
    if pointer_obj.get("operation") != "bucket_pointer_update_last":
        raise MismatchError("pointer object operation drifted")
    if int(receipt.get("pointer_size_bytes") or 0) > MAX_POINTER_BYTES:
        raise MismatchError("pointer is not tiny")
    revalidations = receipt.get("gate_revalidations") or []
    if not isinstance(revalidations, list) or not revalidations:
        raise MismatchError("receipt is missing immediate gate revalidations")
    if revalidations[-1].get("operation") != "bucket_pointer_update_last":
        raise MismatchError("last gate revalidation must be the pointer update")
    if any(
        row.get("operation") == "bucket_pointer_update_last"
        for row in revalidations[:-1]
    ):
        raise MismatchError("pointer update occurred before the last callback")
    if any(row.get("revalidated") is not True for row in revalidations):
        raise MismatchError("a mutation callback skipped immediate gate revalidation")
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


def check_publication_receipt(
    receipt: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    seal_path: Path | str | None = None,
    staging_path: Path | str | None = None,
    candidate_path: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    check_receipt_structure(receipt)
    reject_credentials_in_payload(receipt, label="publication_receipt")
    reject_path_leaks(receipt, label="publication_receipt")
    reject_identity_contamination(receipt, label="publication_receipt")
    fresh = build_default_publication_receipt(
        repo_root=repo_root,
        seal_path=seal_path,
        staging_path=staging_path,
        candidate_path=candidate_path,
        now=now,
    )
    mismatches = compare_receipts(fresh, receipt)
    if mismatches:
        raise StaleInputError(
            "sealed receipt drifted from a fresh publication apply: "
            + "; ".join(mismatches[:8])
        )
    return {
        "bucket_release_prefix": receipt.get("bucket_release_prefix"),
        "criteria": (receipt.get("acceptance") or {}).get("criteria"),
        "dataset_revision": receipt.get("dataset_revision"),
        "deletion_occurred": False,
        "goal_id": receipt.get("goal_id"),
        "identities_digest": receipt.get("identities_digest"),
        "live_network": False,
        "manifest_digest": receipt.get("manifest_digest"),
        "mismatches": [],
        "ok": True,
        "plan_digest": receipt.get("plan_digest"),
        "pointer_updated_last": True,
        "publication_authorized": True,
        "raw_bucket_root_untouched": True,
        "receipt_sha256": receipt.get("receipt_sha256"),
        "remote_object_count": receipt.get("remote_object_count"),
        "root_raw_object_overwritten": False,
        "task_id": receipt.get("task_id"),
    }


def refuse_live_mutation_without_authorization(
    *,
    authorize_mutation: bool,
) -> dict[str, Any]:
    try:
        assert_mutation_authorized(authorize_mutation=authorize_mutation)
    except PublishAuthorizationError as exc:
        return {
            "mutation_authorized": False,
            "mutation_executed": False,
            "remote_write_contacted": False,
            "status": "mutation_refused",
            "reason": str(exc),
            "task_id": TASK_ID,
        }
    return {
        "mutation_authorized": True,
        "mutation_executed": False,
        "remote_write_contacted": False,
        "status": "authorized_but_not_executed",
        "reason": (
            "live Hub mutation requires an operator-injected client; "
            "this CLI applies only through the isolated recorded transport"
        ),
        "task_id": TASK_ID,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="publish_open_us_law_hf_release.py",
        description=(
            "Publish the authorized Open US Law Dataset and content-addressed "
            f"Bucket release ({TASK_ID}). Default mode checks the sealed "
            "publication receipt without network contact."
        ),
    )
    parser.add_argument(
        "--check-receipt",
        action="store_true",
        help="Validate the frozen publication receipt without rewriting it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Emit a reviewed dry-run plan without applying it.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the isolated public publication after a reviewed plan digest.",
    )
    parser.add_argument(
        "--reviewed-plan-digest",
        default=None,
        help="Plan digest that an operator reviewed before --apply.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the publication receipt to --receipt.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help=f"Receipt path (default: {DEFAULT_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--seal",
        type=Path,
        default=None,
        help=f"Prepublication seal (default: {SEAL_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--staging",
        type=Path,
        default=None,
        help=f"Staging receipt (default: {STAGING_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=None,
        help=f"Candidate receipt (default: {CANDIDATE_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--authorize-mutation",
        action="store_true",
        help=(
            "Opt-in live mutation authorization; also requires "
            f"${AUTHORIZATION_ENV}. Isolated apply does not need this flag."
        ),
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Request live Hub mutation (fail-closed unless operator-injected).",
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

    check_receipt = bool(args.check_receipt) or not (
        args.dry_run or args.apply or args.write or args.print_json
    )
    receipt_path = (
        Path(args.receipt).expanduser().resolve()
        if args.receipt is not None
        else default_receipt_path()
    )
    seal_path = (
        Path(args.seal).expanduser().resolve()
        if args.seal is not None
        else default_seal_path()
    )
    staging_path = (
        Path(args.staging).expanduser().resolve()
        if args.staging is not None
        else default_staging_path()
    )
    candidate_path = (
        Path(args.candidate).expanduser().resolve()
        if args.candidate is not None
        else default_candidate_path()
    )

    try:
        if args.live:
            mutation = refuse_live_mutation_without_authorization(
                authorize_mutation=bool(args.authorize_mutation)
            )
            write_json(None, mutation)
            return 2 if mutation["status"] == "mutation_refused" else 0

        if args.dry_run and not args.apply and not args.write:
            seal = load_prepublication_seal(seal_path)
            staging = load_staging_receipt(staging_path)
            candidate = load_candidate_receipt(candidate_path)
            plan = build_publish_plan(
                seal=seal, staging=staging, candidate=candidate, dry_run=True
            )
            payload = build_dry_run_receipt(plan)
            payload["plan"] = {
                "artifacts": [
                    {
                        "relative_path": item["relative_path"],
                        "sha256": item["sha256"],
                    }
                    for item in plan["artifacts"]
                ],
                "bucket_release_prefix": plan["bucket_release_prefix"],
                "dataset_revision": plan["dataset_revision"],
                "manifest_digest": plan["manifest_digest"],
                "operations": plan["operations"],
                "plan_digest": plan["plan_digest"],
                "pointer": plan["pointer"],
                "target_repo": plan["target_repo"],
            }
            write_json(None, payload)
            return 0

        if args.apply or args.write:
            seal = load_prepublication_seal(seal_path)
            staging = load_staging_receipt(staging_path)
            candidate = load_candidate_receipt(candidate_path)
            plan = build_publish_plan(
                seal=seal, staging=staging, candidate=candidate, dry_run=False
            )
            reviewed = args.reviewed_plan_digest or (
                str(plan["plan_digest"]) if args.write and not args.apply else None
            )
            if not reviewed:
                raise PublishPlanReviewError(
                    "apply requires --reviewed-plan-digest matching the dry-run plan"
                )
            raw_root = load_raw_root_snapshot()
            applied = apply_publish_plan(
                plan,
                seal=seal,
                reviewed_plan_digest=str(reviewed),
                raw_root_objects=raw_root,
            )
            receipt = build_publication_receipt(
                plan, applied, seal=seal, staging=staging, candidate=candidate
            )
            if args.write:
                write_json_report(receipt, receipt_path)
            if args.print_json or not args.write:
                write_json(None, receipt)
            return 0

        if check_receipt:
            if not receipt_path.is_file():
                raise MissingInputError(
                    f"publication receipt missing: {DEFAULT_RECEIPT_RELPATH.as_posix()}"
                )
            sealed = load_json_mapping(receipt_path)
            result = check_publication_receipt(
                sealed,
                seal_path=seal_path,
                staging_path=staging_path,
                candidate_path=candidate_path,
            )
            write_json(None, result)
            return 0

        raise PublishOpenUsLawError("no publication action requested")
    except (
        PublishOpenUsLawError,
        PublicationGateDeniedError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
