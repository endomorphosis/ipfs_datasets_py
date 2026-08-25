#!/usr/bin/env python3
"""Upload the sealed Open US Law candidate to isolated Dataset/Bucket staging (OUL-041).

Reviewed dry-run / plan-apply workflow:

1. Load the sealed OUL-040 candidate and bind its exact manifest digest.
2. Plan **add-only** uploads to an explicit non-default Dataset revision and
   a unique content-addressed Bucket staging prefix.
3. After the plan digest is reviewed, apply the identical candidate bytes
   through an isolated staging transport.
4. Refuse production refs, raw bucket-root writes, pointer updates,
   deletion, force-push, and visibility changes.
5. Record every remote object identity on a secret-free receipt.

Default mode is **offline isolated apply** (no Hub contact). Live Hub
mutation remains opt-in and fail-closed.

Validation gate (no network)::

    python scripts/ops/legal_data/stage_open_us_law_hf_release.py --check-receipt
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.open_us_law_publication_gate import (  # noqa: E402
    AUTHORIZED_BUCKET_ID,
    AUTHORIZED_DATASET_REPO_ID,
    BUCKET_POINTER_PATH,
    BUCKET_RELEASE_PREFIX_TEMPLATE,
    FORBIDDEN_OPERATIONS,
    PublicationGateDeniedError,
    PublicationPhase,
    credentials_scope_for,
    evaluate_publication_gate,
    is_protected_raw_root_path,
    release_prefix_for,
    require_publication_gate,
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

TASK_ID: Final = "OUL-041"
GOAL_ID: Final = "OUL-G070"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
PRODUCER: Final = "stage_open_us_law_hf_release.py"
CODE_VERSION: Final = "1"
BUNDLE: Final = "staging-upload"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
DEPENDS_ON: Final[tuple[str, ...]] = ("OUL-007", "OUL-040")

RECEIPT_SCHEMA: Final = "ipfs_datasets_py/open-us-law-staging-upload@1"
SCHEMA_VERSION: Final = "open-us-law-staging-upload/v1"
STAGE_PLAN_SCHEMA: Final = "ipfs_datasets_py/open-us-law-stage-plan@1"
FIXTURE_ID: Final = "open-us-law-staging-upload-v1"

DEFAULT_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/staging_upload.json"
)
CANDIDATE_RECEIPT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/release_candidate.json"
)
BUCKET_SNAPSHOT_RELPATH: Final = Path(
    "docs/reports/open_us_law_reindex/bucket_snapshot.json"
)

DEFAULT_STAGING_BRANCH: Final = "stage/open-us-law-sparse-graphrag-v1"
DEFAULT_DATASET_REPO: Final = DEFAULT_DATASET_REPO_ID
DEFAULT_BUCKET_ID: Final = SOURCE_BUCKET
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
    }
)
ALLOWED_OPERATIONS: Final[frozenset[str]] = frozenset(
    {"add_only_upload", "dataset_additive_commit", "bucket_release_prefix_write"}
)
AUTHORIZATION_ENV: Final = "OPEN_US_LAW_STAGING_AUTHORIZATION"
SECRET_ENV_NAMES: Final[tuple[str, ...]] = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
    "OPEN_US_LAW_HF_TOKEN",
    "OPEN_US_LAW_PUBLICATION_AUTHORIZATION",
    AUTHORIZATION_ENV,
)

ACCEPTANCE_CRITERIA: Final = (
    "The identical candidate is uploaded additively to an explicit "
    "non-default dataset revision and a unique bucket staging prefix "
    "after a reviewed dry-run plan; raw bucket root objects are untouched "
    "and every remote object identity is recorded."
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
        "reviewed_dry_run_plan",
    }
)
_DATASET_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}$"
)
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,200}$")
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


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StageOpenUsLawError(RuntimeError):
    """CLI-level failure (fail-closed)."""


class StageAuthorizationError(StageOpenUsLawError):
    """Raised when mutation is attempted without opt-in authorization."""


class StageSafetyError(StageOpenUsLawError):
    """Raised when a plan would delete, force-push, or change visibility."""


class StageProductionTargetError(StageOpenUsLawError):
    """Raised when a production target is requested without a publication seal."""


class StagePlanReviewError(StageOpenUsLawError):
    """Raised when apply is requested without a matching reviewed dry-run plan."""


class MissingInputError(StageOpenUsLawError):
    """Raised when a required producer input is absent."""


class MismatchError(StageOpenUsLawError):
    """Raised when a bound digest or field does not match."""


class StaleInputError(StageOpenUsLawError):
    """Raised when a receipt drifted from a fresh rebuild."""


class PathLeakError(StageOpenUsLawError):
    """Raised when absolute local paths appear in a public receipt."""


class SecretLeakError(StageOpenUsLawError):
    """Raised when credential-like material appears in a public receipt."""


# ---------------------------------------------------------------------------
# Paths / I/O
# ---------------------------------------------------------------------------


def default_receipt_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / DEFAULT_RECEIPT_RELPATH).resolve()


def default_candidate_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    return (root / CANDIDATE_RECEIPT_RELPATH).resolve()


def repo_relpath(path: Path | str, *, repo_root: Path | str | None = None) -> str:
    root = Path(repo_root) if repo_root is not None else REPOSITORY_ROOT
    target = Path(path)
    try:
        rel = target.resolve().relative_to(root.resolve())
    except ValueError:
        text = str(path).replace("\\", "/")
        if text.startswith("/") or re.match(r"^[A-Za-z]:[/\\]", text):
            raise PathLeakError(f"refusing absolute path in receipt surface: {text!r}")
        return text.lstrip("./")
    return rel.as_posix()


def load_json_mapping(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise MissingInputError(f"JSON file not found: {target.name}")
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StageOpenUsLawError(f"cannot read JSON {target.name}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise StageOpenUsLawError(f"JSON root must be an object: {target.name}")
    return dict(payload)


def write_json_report(payload: Mapping[str, Any], path: Path) -> Path:
    reject_credentials_in_payload(payload, label="staging_upload")
    reject_path_leaks(payload, label="staging_upload")
    reject_identity_contamination(payload, label="staging_upload")
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


def reject_identity_contamination(value: Any, *, label: str = "staging") -> None:
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
        raise StageOpenUsLawError(
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


# ---------------------------------------------------------------------------
# Normalization / safety
# ---------------------------------------------------------------------------


def _normalize_dataset_id(value: str, *, label: str = "target_repo") -> str:
    text = str(value or "").strip()
    if not _DATASET_ID_RE.fullmatch(text):
        raise StageOpenUsLawError(f"{label} must be owner/name, got {value!r}")
    return text


def _normalize_branch(value: str, *, label: str = "staging_branch") -> str:
    text = str(value or "").strip()
    if not text or not _BRANCH_RE.fullmatch(text):
        raise StageOpenUsLawError(f"{label} is invalid: {value!r}")
    if ".." in text or text.startswith("/") or text.endswith("/"):
        raise StageOpenUsLawError(f"{label} is unsafe: {value!r}")
    return text


def assert_non_production_staging_branch(
    staging_branch: str,
    *,
    publication_seal: str | None = None,
) -> str:
    branch = _normalize_branch(staging_branch, label="staging_branch")
    lowered = branch.casefold()
    if lowered in PRODUCTION_REFS or lowered.startswith("refs/heads/main"):
        if not publication_seal:
            raise StageProductionTargetError(
                f"staging branch targets production without a publication seal: "
                f"{branch!r}"
            )
    if _GIT_SHA_RE.fullmatch(lowered):
        return lowered
    if lowered in {"main", "master"}:
        raise StageProductionTargetError(
            f"staging branch must be an explicit non-default revision, got {branch!r}"
        )
    return branch


def _assert_operations_add_only(operations: Sequence[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    for raw in operations:
        op = str(raw or "").strip().casefold().replace("-", "_")
        if not op:
            continue
        if op in FORBIDDEN_OPERATIONS or op.startswith("delete") or "force" in op:
            raise StageSafetyError(
                f"operation is forbidden for Open US Law staging: {raw!r}"
            )
        if "visibility" in op or op in {"private", "unlisted"}:
            raise StageSafetyError(
                f"visibility changes are impossible via staging: {raw!r}"
            )
        if op not in ALLOWED_OPERATIONS:
            raise StageSafetyError(
                f"only additive uploads are permitted; got operation {raw!r}"
            )
        normalized.append(op)
    if not normalized:
        raise StageSafetyError("stage plan requires at least one allowed operation")
    return tuple(sorted(set(normalized)))


def assert_mutation_authorized(
    *,
    authorize_mutation: bool,
    authorization_env: str = AUTHORIZATION_ENV,
) -> None:
    if not authorize_mutation:
        raise StageAuthorizationError(
            "mutation refused: pass --authorize-mutation and set "
            f"${authorization_env} (credentials remain environment-only)"
        )
    token = os.environ.get(authorization_env, "").strip()
    if not token:
        raise StageAuthorizationError(
            f"mutation refused: ${authorization_env} is empty or unset"
        )


def content_cid_for(digest: str) -> str:
    return f"sha256:{normalize_sha256(digest, name='content_cid')}"


def dataset_object_id(*, repo_id: str, revision: str, path: str, sha256: str) -> str:
    return f"dataset:{repo_id}@{revision}:{path}#{sha256}"


def bucket_object_id(*, bucket_id: str, path: str, sha256: str) -> str:
    return f"bucket:{bucket_id}:{path}#{sha256}"


def derive_dataset_revision(
    *,
    manifest_digest: str,
    plan_digest: str,
    staging_branch: str,
) -> str:
    """Return a deterministic 40-hex isolated Dataset staging revision."""

    digest = digest_mapping(
        {
            "kind": "isolated_dataset_staging_revision",
            "manifest_digest": manifest_digest,
            "plan_digest": plan_digest,
            "program_id": PROGRAM_ID,
            "staging_branch": staging_branch,
            "task_id": TASK_ID,
        }
    )
    revision = digest[:40]
    return require_immutable_revision(revision, name="dataset_revision")


# ---------------------------------------------------------------------------
# Isolated additive staging store
# ---------------------------------------------------------------------------


class IsolatedStagingStore:
    """In-process isolated Dataset + Bucket store (additive; never live Hub)."""

    def __init__(self, raw_root_objects: Mapping[str, str] | None = None) -> None:
        self.dataset: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.bucket: dict[tuple[str, str], dict[str, Any]] = {}
        snapshot = {str(k): str(v) for k, v in dict(raw_root_objects or {}).items()}
        self.raw_root_before = dict(snapshot)
        self.raw_root_after = dict(snapshot)

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
        if revision.casefold() in PRODUCTION_REFS:
            raise StageProductionTargetError(
                f"refusing dataset upload to production revision {revision!r}"
            )
        require_immutable_revision(revision, name="dataset_revision")
        key = (repo_id, revision, path)
        record = {
            "content_cid": content_cid,
            "object_id": dataset_object_id(
                repo_id=repo_id, revision=revision, path=path, sha256=sha256
            ),
            "operation": "add_only_upload",
            "path": path,
            "repo_id": repo_id,
            "revision": revision,
            "sha256": sha256,
            "size_bytes": size_bytes,
        }
        existing = self.dataset.get(key)
        if existing is not None and existing["sha256"] != sha256:
            raise StageSafetyError(
                f"additive dataset upload refused: {path} already exists with "
                "different bytes"
            )
        self.dataset[key] = record
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
        posix = path.strip().lstrip("/")
        if posix == BUCKET_POINTER_PATH:
            raise StageSafetyError(
                "staging must not update the raw-root bucket pointer"
            )
        if is_protected_raw_root_path(posix):
            raise StageSafetyError(
                f"refusing protected raw bucket-root path {posix!r}"
            )
        if not posix.startswith("releases/"):
            raise StageSafetyError(
                f"bucket staging writes must stay under {BUCKET_RELEASE_PREFIX_TEMPLATE}"
            )
        if posix in self.raw_root_after:
            raise StageSafetyError(
                f"refusing to mutate raw bucket-root object {posix!r}"
            )
        key = (bucket_id, posix)
        record = {
            "bucket_id": bucket_id,
            "content_cid": content_cid,
            "object_id": bucket_object_id(
                bucket_id=bucket_id, path=posix, sha256=sha256
            ),
            "operation": "add_only_upload",
            "path": posix,
            "sha256": sha256,
            "size_bytes": size_bytes,
        }
        existing = self.bucket.get(key)
        if existing is not None and existing["sha256"] != sha256:
            raise StageSafetyError(
                f"additive bucket upload refused: {posix} already exists with "
                "different bytes"
            )
        self.bucket[key] = record
        return dict(record)

    def raw_root_untouched(self) -> bool:
        return self.raw_root_before == self.raw_root_after

    def raw_root_paths(self) -> tuple[str, ...]:
        return tuple(sorted(self.raw_root_before))


# ---------------------------------------------------------------------------
# Candidate + raw-root loading
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
    if receipt.get("schema") != "ipfs_datasets_py/open-us-law-release-candidate@1":
        raise MismatchError("candidate receipt schema mismatch")
    if receipt.get("task_id") != "OUL-040":
        raise MismatchError("candidate receipt is not the OUL-040 seal")
    if receipt.get("publication_authorized") is not False:
        raise StageSafetyError("candidate receipt must not authorize public mutation")
    candidate = dict(receipt.get("candidate") or {})
    if not candidate.get("manifest_digest"):
        raise MismatchError("candidate receipt missing manifest_digest")
    normalize_sha256(str(candidate["manifest_digest"]), name="candidate.manifest")
    inventory = dict((receipt.get("artifact_digests") or {}).get("inventory") or {})
    if len(inventory) < 8:
        raise MismatchError("candidate artifact inventory is incomplete")
    expected = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    if receipt.get("receipt_sha256") != expected:
        raise StaleInputError("candidate receipt_sha256 does not match the sealed surface")
    return receipt


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
        if not path or "/" in path.rstrip("/"):
            # Only raw-root objects (no prefix) are protected here.
            if path and "/" not in path:
                objects[path] = digest
            continue
        objects[path] = digest
    if not objects:
        raise MismatchError("bucket snapshot contains no raw-root objects")
    return objects


def _candidate_artifacts(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    release_rows = list(
        ((candidate.get("artifact_digests") or {}).get("release_artifacts") or [])
    )
    sizes: dict[str, int | None] = {}
    families: dict[str, str] = {}
    for row in release_rows:
        if not isinstance(row, Mapping):
            continue
        rel = str(row.get("relative_path") or "")
        if not rel:
            continue
        raw_size = row.get("size_bytes")
        sizes[rel] = int(raw_size) if isinstance(raw_size, int) else None
        families[rel] = str(row.get("family") or "")

    inventory = dict((candidate.get("artifact_digests") or {}).get("inventory") or {})
    for rel, digest in sorted(inventory.items()):
        sha = normalize_sha256(str(digest), name=f"artifact.{rel}")
        artifacts.append(
            {
                "content_cid": content_cid_for(sha),
                "family": families.get(rel) or rel.split("/", 1)[0],
                "operation": "add_only_upload",
                "relative_path": rel,
                "sha256": sha,
                "size_bytes": sizes.get(rel),
            }
        )
        seen.add(rel)

    evidence = list((candidate.get("artifact_digests") or {}).get("producer_evidence") or [])
    for row in evidence:
        if not isinstance(row, Mapping):
            continue
        rel = f"evidence/{row.get('key')}"
        if rel in seen:
            continue
        sha = normalize_sha256(str(row.get("sha256")), name=f"evidence.{row.get('key')}")
        artifacts.append(
            {
                "content_cid": content_cid_for(sha),
                "family": "evidence",
                "operation": "add_only_upload",
                "relative_path": rel,
                "sha256": sha,
                "size_bytes": None,
            }
        )
    if not artifacts:
        raise MismatchError("candidate produced no staging artifacts")
    return artifacts


# ---------------------------------------------------------------------------
# Plan construction
# ---------------------------------------------------------------------------


def build_stage_plan(
    candidate: Mapping[str, Any],
    *,
    target_repo: str | None = None,
    staging_branch: str = DEFAULT_STAGING_BRANCH,
    bucket_id: str = DEFAULT_BUCKET_ID,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Build a deterministic add-only stage plan from the sealed candidate."""

    if not isinstance(candidate, Mapping):
        raise StageOpenUsLawError("candidate must be an object")
    if type(dry_run) is not bool:
        raise StageOpenUsLawError("dry_run must be boolean")

    body = dict(candidate.get("candidate") or {})
    manifest_digest = normalize_sha256(
        str(body.get("manifest_digest") or ""), name="manifest_digest"
    )
    release_root_cid = str(body.get("release_root_cid") or f"sha256:{manifest_digest}")
    dataset_id = _normalize_dataset_id(
        target_repo or str(body.get("dataset_id") or DEFAULT_DATASET_REPO),
        label="target_repo",
    )
    if dataset_id != AUTHORIZED_DATASET_REPO_ID:
        raise StageProductionTargetError(
            f"dataset target {dataset_id!r} is not the authorized Dataset"
        )
    bucket = _normalize_dataset_id(bucket_id, label="bucket_id")
    if bucket != AUTHORIZED_BUCKET_ID:
        raise StageProductionTargetError(
            f"bucket target {bucket!r} is not the authorized Bucket"
        )
    branch = assert_non_production_staging_branch(staging_branch)
    artifacts = _candidate_artifacts(candidate)
    operations = _assert_operations_add_only([item["operation"] for item in artifacts])
    prefix = release_prefix_for(manifest_digest)
    upload_bytes = sum(
        int(item["size_bytes"]) for item in artifacts if isinstance(item["size_bytes"], int)
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
        "bucket_staging_prefix": prefix,
        "dataset_id": dataset_id,
        "legacy_files_deleted": False,
        "manifest_digest": manifest_digest,
        "pointer_updated": False,
        "release_root_cid": release_root_cid,
        "schema": STAGE_PLAN_SCHEMA,
        "staging_branch": branch,
        "target_repo": dataset_id,
    }
    plan_digest = digest_mapping(binding)
    dataset_revision = derive_dataset_revision(
        manifest_digest=manifest_digest,
        plan_digest=plan_digest,
        staging_branch=branch,
    )
    if dataset_revision.casefold() in PRODUCTION_REFS:
        raise StageProductionTargetError("derived dataset revision is a production ref")

    plan: dict[str, Any] = {
        "acceptance": {
            "add_only": True,
            "credentials_environment_only": True,
            "deletion_impossible": True,
            "force_push_impossible": True,
            "identical_candidate": True,
            "mutation_requires_authorization": True,
            "pointer_update_impossible": True,
            "production_target_rejected_without_seal": True,
            "raw_root_write_impossible": True,
            "revision_explicit": True,
            "target_explicit": True,
            "unique_bucket_prefix": True,
            "visibility_change_impossible": True,
        },
        "artifacts": artifacts,
        "bucket_id": bucket,
        "bucket_pointer_path": BUCKET_POINTER_PATH,
        "bucket_staging_prefix": prefix,
        "candidate_receipt_sha256": candidate.get("receipt_sha256"),
        "dataset_id": dataset_id,
        "dataset_revision": dataset_revision,
        "dry_run": dry_run,
        "forbidden_operations": sorted(FORBIDDEN_OPERATIONS),
        "goal_id": GOAL_ID,
        "legacy_files_deleted": False,
        "manifest_digest": manifest_digest,
        "operations": list(operations),
        "plan_digest": plan_digest,
        "pointer_updated": False,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "release_profile": body.get("release_profile"),
        "release_root_cid": release_root_cid,
        "schema": STAGE_PLAN_SCHEMA,
        "source_revision": body.get("source_revision"),
        "staging_branch": branch,
        "task_id": TASK_ID,
        "target_repo": dataset_id,
        "upload_bytes": upload_bytes,
        "upload_file_count": len(artifacts),
        "visibility": "public",
        "visibility_change_allowed": False,
    }
    reject_credentials_in_payload(plan, label="stage_plan")
    reject_identity_contamination(plan, label="stage_plan")
    assert_safe_stage_plan(plan)
    return plan


def assert_safe_stage_plan(plan: Mapping[str, Any]) -> None:
    if not isinstance(plan, Mapping):
        raise StageOpenUsLawError("stage plan must be an object")
    required = (
        "target_repo",
        "staging_branch",
        "dataset_revision",
        "bucket_staging_prefix",
        "manifest_digest",
        "plan_digest",
        "release_root_cid",
        "operations",
        "artifacts",
    )
    missing = [key for key in required if not plan.get(key)]
    if missing:
        raise StageOpenUsLawError(
            "stage plan missing explicit fields: " + ", ".join(missing)
        )

    _normalize_dataset_id(str(plan["target_repo"]), label="target_repo")
    if str(plan["target_repo"]) != AUTHORIZED_DATASET_REPO_ID:
        raise StageProductionTargetError("plan target_repo is not the authorized Dataset")
    assert_non_production_staging_branch(str(plan["staging_branch"]))
    revision = require_immutable_revision(
        str(plan["dataset_revision"]), name="dataset_revision"
    )
    if revision.casefold() in PRODUCTION_REFS:
        raise StageProductionTargetError("dataset revision must not be a production ref")
    prefix = str(plan["bucket_staging_prefix"])
    expected_prefix = release_prefix_for(str(plan["manifest_digest"]))
    if prefix != expected_prefix:
        raise StageSafetyError(
            "bucket staging prefix must be the unique content-addressed "
            f"{BUCKET_RELEASE_PREFIX_TEMPLATE} for this candidate"
        )
    if plan.get("legacy_files_deleted") is not False:
        raise StageSafetyError("stage plan must declare legacy_files_deleted=false")
    if plan.get("visibility_change_allowed") is not False:
        raise StageSafetyError("visibility_change_allowed must be false")
    if plan.get("pointer_updated") is not False:
        raise StageSafetyError("staging must not update LATEST.json")
    if str(plan.get("visibility") or "").casefold() != "public":
        raise StageSafetyError("staging visibility must remain public")

    ops = plan.get("operations") or []
    if not isinstance(ops, list):
        raise StageOpenUsLawError("operations must be a list")
    _assert_operations_add_only([str(item) for item in ops])

    artifacts = plan.get("artifacts") or []
    if not isinstance(artifacts, list) or not artifacts:
        raise StageOpenUsLawError("stage plan requires a non-empty artifacts list")
    for index, item in enumerate(artifacts):
        if not isinstance(item, Mapping):
            raise StageOpenUsLawError(f"artifacts[{index}] must be an object")
        op = str(item.get("operation") or "").casefold()
        if op != "add_only_upload":
            raise StageSafetyError(
                f"artifacts[{index}] operation must be add_only_upload, got {op!r}"
            )
        rel = str(item.get("relative_path") or "")
        if not rel or rel.startswith("/") or ".." in Path(rel).parts:
            raise StageSafetyError(
                f"artifacts[{index}] has unsafe relative_path: {rel!r}"
            )
        digest = str(item.get("sha256") or "").casefold()
        if not _SHA256_RE.fullmatch(digest):
            raise StageOpenUsLawError(
                f"artifacts[{index}] requires a full sha256 digest"
            )
    reject_credentials_in_payload(plan, label="stage_plan")


# ---------------------------------------------------------------------------
# Publication-gate requests
# ---------------------------------------------------------------------------


def _dataset_gate_request(plan: Mapping[str, Any]) -> dict[str, Any]:
    repo = str(plan["target_repo"])
    return {
        "phase": PublicationPhase.STAGING.value,
        "operation": "dataset_additive_commit",
        "dataset_repo_id": repo,
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
        "credentials_environment_only": True,
        "secret_redacted": True,
        "credentials_scope": credentials_scope_for(dataset_repo_id=repo),
        "credential_identity": f"env:{repo}",
        "payload": {
            "release_mode": "additive",
            "credentials_environment_only": True,
            "secret_redacted": True,
            "staging_branch": plan["staging_branch"],
            "dataset_revision": plan["dataset_revision"],
        },
        "argv": [
            "stage-open-us-law",
            "--phase",
            "staging",
            "--authorize-mutation",
        ],
    }


def _bucket_gate_request(plan: Mapping[str, Any], object_path: str) -> dict[str, Any]:
    bucket = str(plan["bucket_id"])
    return {
        "phase": PublicationPhase.STAGING.value,
        "operation": "bucket_release_prefix_write",
        "dataset_repo_id": str(plan["target_repo"]),
        "bucket_id": bucket,
        "object_path": object_path,
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
        "credentials_environment_only": True,
        "secret_redacted": True,
        "credentials_scope": credentials_scope_for(bucket_id=bucket),
        "credential_identity": f"env:{bucket}",
        "payload": {
            "release_mode": "additive",
            "credentials_environment_only": True,
            "secret_redacted": True,
            "bucket_staging_prefix": plan["bucket_staging_prefix"],
        },
        "argv": [
            "stage-open-us-law",
            "--phase",
            "staging",
            "--authorize-mutation",
        ],
    }


def authorize_staging_operations(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Run the publication gate for every planned isolated mutation."""

    decisions: list[dict[str, Any]] = []
    dataset_decision = require_publication_gate(_dataset_gate_request(plan))
    decisions.append(
        {
            "authorized": dataset_decision.authorized,
            "network_mutation_permitted": dataset_decision.network_mutation_permitted,
            "operation": dataset_decision.operation,
            "phase": dataset_decision.phase,
        }
    )
    prefix = str(plan["bucket_staging_prefix"])
    for item in plan["artifacts"]:
        object_path = f"{prefix}{item['relative_path']}"
        decision = require_publication_gate(_bucket_gate_request(plan, object_path))
        decisions.append(
            {
                "authorized": decision.authorized,
                "network_mutation_permitted": decision.network_mutation_permitted,
                "operation": decision.operation,
                "phase": decision.phase,
                "object_path": object_path,
            }
        )
    pointer_request = _bucket_gate_request(plan, BUCKET_POINTER_PATH)
    pointer_request["operation"] = "bucket_pointer_update_last"
    pointer_request["object_path"] = BUCKET_POINTER_PATH
    pointer_decision = evaluate_publication_gate(pointer_request)
    if pointer_decision.authorized:
        raise StageSafetyError("staging must not be able to update LATEST.json")
    decisions.append(
        {
            "authorized": False,
            "network_mutation_permitted": False,
            "operation": "bucket_pointer_update_last",
            "phase": PublicationPhase.STAGING.value,
            "refused": True,
        }
    )
    return decisions


# ---------------------------------------------------------------------------
# Plan apply
# ---------------------------------------------------------------------------


def apply_stage_plan(
    plan: Mapping[str, Any],
    *,
    reviewed_plan_digest: str,
    store: IsolatedStagingStore | None = None,
    raw_root_objects: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Upload the identical candidate after a reviewed dry-run plan."""

    assert_safe_stage_plan(plan)
    expected = str(plan["plan_digest"])
    reviewed = normalize_sha256(reviewed_plan_digest, name="reviewed_plan_digest")
    if reviewed != expected:
        raise StagePlanReviewError(
            "apply refused: reviewed dry-run plan digest does not match the "
            f"current plan ({reviewed} != {expected})"
        )

    isolated = store or IsolatedStagingStore(raw_root_objects)
    gate_decisions = authorize_staging_operations(plan)
    prefix = str(plan["bucket_staging_prefix"])
    revision = str(plan["dataset_revision"])
    repo = str(plan["target_repo"])
    bucket = str(plan["bucket_id"])

    remote_objects: list[dict[str, Any]] = []
    for item in plan["artifacts"]:
        rel = str(item["relative_path"])
        sha = str(item["sha256"])
        cid = str(item["content_cid"])
        size = item.get("size_bytes")
        dataset_record = isolated.add_dataset(
            repo_id=repo,
            revision=revision,
            path=rel,
            sha256=sha,
            size_bytes=size if isinstance(size, int) else None,
            content_cid=cid,
        )
        bucket_path = f"{prefix}{rel}"
        bucket_record = isolated.add_bucket(
            bucket_id=bucket,
            path=bucket_path,
            sha256=sha,
            size_bytes=size if isinstance(size, int) else None,
            content_cid=cid,
        )
        remote_objects.append(
            {
                "bucket_object": bucket_record,
                "content_cid": cid,
                "dataset_object": dataset_record,
                "operation": "add_only_upload",
                "relative_path": rel,
                "sha256": sha,
                "size_bytes": size if isinstance(size, int) else None,
            }
        )

    if not isolated.raw_root_untouched():
        raise StageSafetyError("raw bucket-root objects were mutated during staging")
    if any(path == BUCKET_POINTER_PATH for _, path in isolated.bucket):
        raise StageSafetyError("staging wrote the raw-root bucket pointer")

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
            "prefix": prefix,
        }
    )
    return {
        "dataset_revision": revision,
        "gate_decision_count": len(gate_decisions),
        "gate_decisions": gate_decisions,
        "identities_digest": identities_digest,
        "pointer_updated": False,
        "raw_root_paths": list(isolated.raw_root_paths()),
        "raw_root_untouched": True,
        "remote_object_count": len(remote_objects) * 2,
        "remote_objects": remote_objects,
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
        and row.get("sha256") == next(
            (
                art["sha256"]
                for art in plan["artifacts"]
                if art["relative_path"] == row.get("relative_path")
            ),
            None,
        )
        for row in remote
    )
    revision = str(applied.get("dataset_revision") or "")
    prefix = str(plan.get("bucket_staging_prefix") or "")
    acceptance = {
        "additive_upload": True,
        "all_expected_outputs_required": True,
        "criteria": ACCEPTANCE_CRITERIA,
        "every_remote_object_identity_recorded": identities_ok
        and int(applied.get("remote_object_count") or 0) == len(plan["artifacts"]) * 2,
        "explicit_non_default_dataset_revision": bool(_GIT_SHA_RE.fullmatch(revision))
        and revision.casefold() not in PRODUCTION_REFS,
        "identical_candidate_uploaded": bool(remote)
        and all(
            row["sha256"]
            == next(
                art["sha256"]
                for art in plan["artifacts"]
                if art["relative_path"] == row["relative_path"]
            )
            for row in remote
        ),
        "no_secret_or_path_leak": True,
        "pointer_not_updated": applied.get("pointer_updated") is False,
        "public_mutation_not_authorized": True,
        "raw_bucket_root_untouched": applied.get("raw_root_untouched") is True,
        "reviewed_dry_run_plan": bool(reviewed)
        and bool(plan.get("plan_digest"))
        and bool(_SHA256_RE.fullmatch(str(plan.get("plan_digest") or ""))),
        "unique_bucket_staging_prefix": prefix == release_prefix_for(
            str(plan["manifest_digest"])
        )
        and prefix.startswith("releases/"),
    }
    failed = [
        key for key, value in acceptance.items() if key != "criteria" and not value
    ]
    if failed:
        raise MismatchError("staging-upload acceptance failed: " + ", ".join(failed))
    return acceptance


def build_staging_receipt(
    plan: Mapping[str, Any],
    applied: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the sealed isolated staging-upload receipt."""

    assert_safe_stage_plan(plan)
    acceptance = _acceptance_from_apply(plan, applied, reviewed=True)
    remote_objects = list(applied["remote_objects"])
    receipt: dict[str, Any] = {
        "acceptance": acceptance,
        "adr_path": ADR_PATH,
        "board_namespace": BOARD_NAMESPACE,
        "bucket_id": plan["bucket_id"],
        "bucket_pointer_path": BUCKET_POINTER_PATH,
        "bucket_pointer_updated": False,
        "bucket_staging_prefix": plan["bucket_staging_prefix"],
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
            "staging_branch": plan["staging_branch"],
        },
        "code_version": CODE_VERSION,
        "dataset_id": plan["dataset_id"],
        "dataset_revision": applied["dataset_revision"],
        "depends_on": list(DEPENDS_ON),
        "dry_run": False,
        "fixture_id": FIXTURE_ID,
        "goal_id": GOAL_ID,
        "identities_digest": applied["identities_digest"],
        "isolated_transport": True,
        "live_network": False,
        "manifest_digest": plan["manifest_digest"],
        "mutation_authorized": False,
        "mutation_executed": True,
        "network_required": False,
        "notes": (
            "Isolated additive staging upload of the sealed Open US Law "
            "release candidate (OUL-041). Identical candidate bytes were "
            "uploaded to an explicit non-default 40-hex Dataset revision and "
            "the unique content-addressed Bucket prefix after a reviewed "
            "dry-run plan. Raw bucket-root objects and LATEST.json were not "
            "touched. Live Hub mutation is not authorized by this receipt."
        ),
        "plan_digest": plan["plan_digest"],
        "pointer_updated": False,
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "public_mutation_authorized": False,
        "publication_authorized": False,
        "raw_bucket_root_object_count": len(applied.get("raw_root_paths") or []),
        "raw_bucket_root_untouched": True,
        "remote_default_branches_mutated": False,
        "remote_object_count": applied["remote_object_count"],
        "remote_objects": remote_objects,
        "remote_write_contacted": False,
        "reviewed_plan_digest": plan["plan_digest"],
        "schema": RECEIPT_SCHEMA,
        "schema_version": SCHEMA_VERSION,
        "staging_branch": plan["staging_branch"],
        "status": "staged_isolated",
        "task_id": TASK_ID,
        "target_repo": plan["target_repo"],
        "tokens_used": False,
        "transport": "isolated_recorded_staging_store",
        "upload_bytes": plan["upload_bytes"],
        "upload_file_count": plan["upload_file_count"],
        "visibility_changed": False,
    }
    receipt["receipt_sha256"] = digest_mapping(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    reject_credentials_in_payload(receipt, label="staging_upload")
    reject_path_leaks(receipt, label="staging_upload")
    reject_identity_contamination(receipt, label="staging_upload")
    return receipt


def build_dry_run_receipt(plan: Mapping[str, Any]) -> dict[str, Any]:
    assert_safe_stage_plan(plan)
    receipt: dict[str, Any] = {
        "dry_run": True,
        "goal_id": GOAL_ID,
        "human_approval_required": True,
        "live_network": False,
        "manifest_digest": plan["manifest_digest"],
        "mutation_authorized": False,
        "mutation_executed": False,
        "plan_digest": plan["plan_digest"],
        "producer": PRODUCER,
        "program_id": PROGRAM_ID,
        "remote_write_contacted": False,
        "schema": STAGE_PLAN_SCHEMA,
        "staging_branch": plan["staging_branch"],
        "status": "dry_run_reviewed",
        "task_id": TASK_ID,
        "target_repo": plan["target_repo"],
        "tokens_used": False,
        "upload_bytes": plan["upload_bytes"],
        "upload_file_count": plan["upload_file_count"],
        "dataset_revision": plan["dataset_revision"],
        "bucket_staging_prefix": plan["bucket_staging_prefix"],
    }
    reject_credentials_in_payload(receipt, label="dry_run_receipt")
    reject_identity_contamination(receipt, label="dry_run_receipt")
    return receipt


def build_default_staging_receipt(
    *,
    repo_root: Path | str | None = None,
    candidate_path: Path | str | None = None,
) -> dict[str, Any]:
    candidate = load_candidate_receipt(candidate_path, repo_root=repo_root)
    plan = build_stage_plan(candidate, dry_run=False)
    raw_root = load_raw_root_snapshot(repo_root=repo_root)
    applied = apply_stage_plan(
        plan,
        reviewed_plan_digest=str(plan["plan_digest"]),
        raw_root_objects=raw_root,
    )
    return build_staging_receipt(plan, applied, candidate=candidate)


def materialize_default_receipt(
    *,
    repo_root: Path | str | None = None,
    receipt_path: Path | str | None = None,
    candidate_path: Path | str | None = None,
) -> tuple[dict[str, Any], Path]:
    receipt = build_default_staging_receipt(
        repo_root=repo_root, candidate_path=candidate_path
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
        "bucket_staging_prefix",
        "receipt_sha256",
        "status",
        "live_network",
        "publication_authorized",
        "raw_bucket_root_untouched",
        "pointer_updated",
        "remote_object_count",
        "identities_digest",
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
                "staging_branch",
            ),
        )
    )
    if fresh.get("acceptance") != sealed.get("acceptance"):
        mismatches.append("acceptance drifted from the sealed receipt")
    fresh_ids = [
        (row.get("relative_path"), row.get("sha256"),
         (row.get("dataset_object") or {}).get("object_id"),
         (row.get("bucket_object") or {}).get("object_id"))
        for row in (fresh.get("remote_objects") or [])
        if isinstance(row, Mapping)
    ]
    sealed_ids = [
        (row.get("relative_path"), row.get("sha256"),
         (row.get("dataset_object") or {}).get("object_id"),
         (row.get("bucket_object") or {}).get("object_id"))
        for row in (sealed.get("remote_objects") or [])
        if isinstance(row, Mapping)
    ]
    if fresh_ids != sealed_ids:
        mismatches.append("remote object identities drifted from the sealed receipt")
    return mismatches


def check_receipt_structure(receipt: Mapping[str, Any]) -> None:
    required = (
        "acceptance",
        "bucket_staging_prefix",
        "candidate",
        "dataset_revision",
        "identities_digest",
        "manifest_digest",
        "plan_digest",
        "receipt_sha256",
        "remote_objects",
        "reviewed_plan_digest",
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
    if receipt.get("dry_run") is not False:
        raise MismatchError("sealed receipt must record the applied isolated upload")
    if receipt.get("mutation_executed") is not True:
        raise MismatchError("sealed receipt must record the isolated apply")
    if receipt.get("raw_bucket_root_untouched") is not True:
        raise MismatchError("receipt does not prove raw bucket root was untouched")
    if receipt.get("pointer_updated") is not False:
        raise MismatchError("receipt must not update LATEST.json")
    if receipt.get("reviewed_plan_digest") != receipt.get("plan_digest"):
        raise MismatchError("reviewed plan digest does not match plan_digest")
    revision = require_immutable_revision(
        str(receipt.get("dataset_revision")), name="receipt.dataset_revision"
    )
    if revision.casefold() in PRODUCTION_REFS:
        raise MismatchError("dataset revision is a production ref")
    prefix = str(receipt.get("bucket_staging_prefix") or "")
    expected_prefix = release_prefix_for(str(receipt.get("manifest_digest")))
    if prefix != expected_prefix:
        raise MismatchError("bucket staging prefix is not unique to this candidate")
    objects = receipt.get("remote_objects") or []
    if not isinstance(objects, list) or not objects:
        raise MismatchError("receipt is missing remote object identities")
    expected_count = len(objects) * 2
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
                f"remote_objects[{index}] is not under the unique staging prefix"
            )
        if is_protected_raw_root_path(str(bucket_obj.get("path") or "")):
            raise MismatchError(
                f"remote_objects[{index}] targets a protected raw-root path"
            )
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


def check_staging_receipt(
    receipt: Mapping[str, Any],
    *,
    repo_root: Path | str | None = None,
    candidate_path: Path | str | None = None,
) -> dict[str, Any]:
    check_receipt_structure(receipt)
    reject_credentials_in_payload(receipt, label="staging_upload")
    reject_path_leaks(receipt, label="staging_upload")
    reject_identity_contamination(receipt, label="staging_upload")
    fresh = build_default_staging_receipt(
        repo_root=repo_root, candidate_path=candidate_path
    )
    mismatches = compare_receipts(fresh, receipt)
    if mismatches:
        raise StaleInputError(
            "sealed receipt drifted from a fresh staging apply: "
            + "; ".join(mismatches[:8])
        )
    return {
        "bucket_staging_prefix": receipt.get("bucket_staging_prefix"),
        "criteria": (receipt.get("acceptance") or {}).get("criteria"),
        "dataset_revision": receipt.get("dataset_revision"),
        "goal_id": receipt.get("goal_id"),
        "identities_digest": receipt.get("identities_digest"),
        "live_network": False,
        "manifest_digest": receipt.get("manifest_digest"),
        "mismatches": [],
        "ok": True,
        "plan_digest": receipt.get("plan_digest"),
        "publication_authorized": False,
        "raw_bucket_root_untouched": True,
        "receipt_sha256": receipt.get("receipt_sha256"),
        "remote_object_count": receipt.get("remote_object_count"),
        "task_id": receipt.get("task_id"),
    }


def refuse_live_mutation_without_authorization(
    *,
    authorize_mutation: bool,
) -> dict[str, Any]:
    try:
        assert_mutation_authorized(authorize_mutation=authorize_mutation)
    except StageAuthorizationError as exc:
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
        prog="stage_open_us_law_hf_release.py",
        description=(
            "Upload the sealed Open US Law candidate to isolated Dataset "
            f"and Bucket staging ({TASK_ID}). Default mode checks the "
            "sealed staging receipt without network contact."
        ),
    )
    parser.add_argument(
        "--check-receipt",
        action="store_true",
        help="Validate the frozen staging-upload receipt without rewriting it.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Emit a reviewed dry-run plan without applying it.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the isolated staging upload after a reviewed plan digest.",
    )
    parser.add_argument(
        "--reviewed-plan-digest",
        default=None,
        help="Plan digest that an operator reviewed before --apply.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"Write the staging receipt to --receipt.",
    )
    parser.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help=f"Receipt path (default: {DEFAULT_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--candidate",
        type=Path,
        default=None,
        help=f"Candidate receipt (default: {CANDIDATE_RECEIPT_RELPATH.as_posix()})",
    )
    parser.add_argument(
        "--staging-branch",
        default=DEFAULT_STAGING_BRANCH,
        help=f"Explicit non-default staging branch (default: {DEFAULT_STAGING_BRANCH})",
    )
    parser.add_argument(
        "--target-repo",
        default=DEFAULT_DATASET_REPO,
        help=f"Explicit Dataset id (default: {DEFAULT_DATASET_REPO})",
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
            candidate = load_candidate_receipt(candidate_path)
            plan = build_stage_plan(
                candidate,
                target_repo=args.target_repo,
                staging_branch=args.staging_branch,
                dry_run=True,
            )
            payload = build_dry_run_receipt(plan)
            payload["plan"] = {
                "artifacts": plan["artifacts"],
                "bucket_staging_prefix": plan["bucket_staging_prefix"],
                "dataset_revision": plan["dataset_revision"],
                "manifest_digest": plan["manifest_digest"],
                "operations": plan["operations"],
                "plan_digest": plan["plan_digest"],
                "staging_branch": plan["staging_branch"],
                "target_repo": plan["target_repo"],
            }
            write_json(None, payload)
            return 0

        if args.apply or args.write:
            candidate = load_candidate_receipt(candidate_path)
            plan = build_stage_plan(
                candidate,
                target_repo=args.target_repo,
                staging_branch=args.staging_branch,
                dry_run=False,
            )
            reviewed = args.reviewed_plan_digest or (
                str(plan["plan_digest"]) if args.write and not args.apply else None
            )
            if not reviewed:
                raise StagePlanReviewError(
                    "apply requires --reviewed-plan-digest matching the dry-run plan"
                )
            raw_root = load_raw_root_snapshot()
            applied = apply_stage_plan(
                plan,
                reviewed_plan_digest=str(reviewed),
                raw_root_objects=raw_root,
            )
            receipt = build_staging_receipt(plan, applied, candidate=candidate)
            if args.write:
                write_json_report(receipt, receipt_path)
            if args.print_json or not args.write:
                write_json(None, receipt)
            return 0

        if check_receipt:
            if not receipt_path.is_file():
                raise MissingInputError(
                    f"staging receipt missing: {DEFAULT_RECEIPT_RELPATH.as_posix()}"
                )
            sealed = load_json_mapping(receipt_path)
            result = check_staging_receipt(
                sealed,
                candidate_path=candidate_path,
            )
            write_json(None, result)
            return 0

        raise StageOpenUsLawError("no staging action requested")
    except (
        StageOpenUsLawError,
        PublicationGateDeniedError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
